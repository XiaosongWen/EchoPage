"""Audio chapter splitting and resampling module for EchoPage."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence, Union

log = logging.getLogger("echopage.audio")


class AudioError(RuntimeError):
    """Raised when an audio processing or conversion step fails."""


class ChapterDict(dict):
    """Dictionary representing chapter info with attribute access."""

    @property
    def title(self) -> str:
        return str(self.get("title", ""))

    @property
    def start_s(self) -> float:
        return float(self.get("start_s", 0.0))

    @property
    def end_s(self) -> float:
        return float(self.get("end_s", 0.0))


@dataclass
class AudioUnit:
    """Represents a discrete audio unit aligned to an EPUB chapter or segment."""

    path: Path
    start_s: float
    end_s: float
    title: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            self.path = Path(self.path)
        self.start_s = float(self.start_s)
        self.end_s = float(self.end_s)
        self.title = str(self.title)

    @property
    def duration(self) -> float:
        """Duration of this audio unit in seconds."""
        return max(0.0, self.end_s - self.start_s)

    def __iter__(self):
        """Allow tuple unpacking: path, start_s, end_s, title = unit."""
        yield self.path
        yield self.start_s
        yield self.end_s
        yield self.title

    def __getitem__(self, item: Union[int, str]) -> Any:
        """Allow indexing as tuple or dict."""
        if isinstance(item, int):
            return (self.path, self.start_s, self.end_s, self.title)[item]
        if isinstance(item, str):
            if hasattr(self, item):
                return getattr(self, item)
        raise KeyError(item)


def _parse_time_val(
    time_str: Any,
    time_ticks: Any,
    time_base: str | None,
) -> float:
    """Parse timestamp into float seconds from either string or tick/base ratio."""
    if time_str is not None:
        try:
            return float(time_str)
        except (ValueError, TypeError):
            pass
    if time_ticks is not None and time_base:
        try:
            num, den = str(time_base).split("/")
            return float(time_ticks) * float(num) / float(den)
        except Exception:
            pass
    if time_ticks is not None:
        try:
            return float(time_ticks)
        except (ValueError, TypeError):
            pass
    return 0.0


def parse_chapters_json(
    data: Union[dict, str],
    fallback_duration: float | None = None,
    fallback_title: str | None = None,
) -> list[ChapterDict]:
    """Parse chapter information from ffprobe JSON data or string.

    If chapters are present, returns a list of chapter dicts with
    ``title``, ``start_s``, and ``end_s``. If chapters are empty,
    returns a single unit covering the total duration.
    """
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            raise AudioError(f"Failed to parse ffprobe JSON: {exc}") from exc
    elif isinstance(data, dict):
        parsed = data
    else:
        raise TypeError(f"Expected dict or str for JSON data, got {type(data).__name__}")

    raw_chapters = parsed.get("chapters", [])
    format_info = parsed.get("format", {})
    format_tags = format_info.get("tags", {}) or {}

    # Extract overall format duration if available
    fmt_duration = None
    if "duration" in format_info:
        try:
            fmt_duration = float(format_info["duration"])
        except (ValueError, TypeError):
            pass

    default_title = (
        fallback_title
        or format_tags.get("title")
        or "Chapter 1"
    )

    if raw_chapters:
        result: list[ChapterDict] = []
        for i, ch in enumerate(raw_chapters):
            ch_tags = ch.get("tags", {}) or {}
            title = ch_tags.get("title") or f"Chapter {i + 1}"
            start_s = _parse_time_val(
                ch.get("start_time"),
                ch.get("start"),
                ch.get("time_base"),
            )
            end_s = _parse_time_val(
                ch.get("end_time"),
                ch.get("end"),
                ch.get("time_base"),
            )
            result.append(
                ChapterDict({
                    "title": str(title),
                    "start_s": round(start_s, 6),
                    "end_s": round(end_s, 6),
                })
            )
        return result

    # No chapters: treat file as one unit
    duration = (
        fmt_duration
        if fmt_duration is not None
        else (fallback_duration if fallback_duration is not None else 0.0)
    )

    return [
        ChapterDict({
            "title": str(default_title),
            "start_s": 0.0,
            "end_s": round(duration, 6),
        })
    ]


def probe_chapters(path: str | Path) -> list[ChapterDict]:
    """Probe an audio file for chapters using ffprobe.

    Uses ``ffprobe -show_chapters -of json`` (along with format duration).
    Returns a list of dicts: ``[{'title': ..., 'start_s': ..., 'end_s': ...}]``.
    If there are no embedded chapters, returns a single unit covering the whole file.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")

    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        raise AudioError("ffprobe is not installed or not found on PATH")

    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_chapters",
        "-show_entries",
        "format=duration:format_tags=title",
        "-of",
        "json",
        str(file_path),
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as exc:
        raise AudioError(f"Failed to execute ffprobe: {exc}") from exc

    if res.returncode != 0:
        stderr_msg = res.stderr.strip() if res.stderr else "Unknown error"
        raise AudioError(f"ffprobe failed with exit code {res.returncode}:\n{stderr_msg}")

    return parse_chapters_json(
        res.stdout,
        fallback_title=file_path.stem,
    )


def split_audio(
    path: str | Path,
    chapters: Sequence[dict | ChapterDict | AudioUnit] | None = None,
    out_dir: str | Path | None = None,
) -> list[AudioUnit]:
    """Split an audio file into chapter segments using stream copying.

    Cuts using ``ffmpeg -ss <start> -to <end> -i in -c copy part_N.m4b`` (or mp3).
    Returns a list of ``AudioUnit(path, start_s, end_s, title)`` objects.
    """
    in_path = Path(path)
    if not in_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")

    target_dir = Path(out_dir or in_path.parent)
    target_dir.mkdir(parents=True, exist_ok=True)

    if chapters is None:
        chapter_list = probe_chapters(in_path)
    else:
        chapter_list = list(chapters)

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise AudioError("ffmpeg is not installed or not found on PATH")

    ext = in_path.suffix.lower() if in_path.suffix else ".m4b"
    units: list[AudioUnit] = []

    for i, ch in enumerate(chapter_list):
        if isinstance(ch, dict):
            title = str(ch.get("title", f"Chapter {i + 1}"))
            start_s = float(ch.get("start_s", 0.0))
            end_s = float(ch.get("end_s", 0.0))
        elif hasattr(ch, "start_s") and hasattr(ch, "end_s"):
            title = str(getattr(ch, "title", f"Chapter {i + 1}"))
            start_s = float(getattr(ch, "start_s", 0.0))
            end_s = float(getattr(ch, "end_s", 0.0))
        else:
            raise TypeError(f"Unsupported chapter format at index {i}: {type(ch)}")

        part_filename = f"part_{i}{ext}"
        out_part_path = target_dir / part_filename

        # Caching: reuse existing split part if already generated
        if out_part_path.is_file() and out_part_path.stat().st_size > 0:
            log.info("Using cached split part: %s", out_part_path)
            units.append(
                AudioUnit(
                    path=out_part_path,
                    start_s=start_s,
                    end_s=end_s,
                    title=title,
                )
            )
            continue

        cmd = [
            ffmpeg_bin,
            "-y",
            "-ss",
            f"{start_s:.6f}",
            "-to",
            f"{end_s:.6f}",
            "-i",
            str(in_path),
            "-c",
            "copy",
            str(out_part_path),
        ]

        log.debug("Splitting audio chapter %d: %s", i, " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

        # Fallback to standard re-encode if stream copy fails
        if proc.returncode != 0:
            log.debug("Stream copy failed; attempting transcode fallback for %s", out_part_path)
            cmd_fallback = [
                ffmpeg_bin,
                "-y",
                "-ss",
                f"{start_s:.6f}",
                "-to",
                f"{end_s:.6f}",
                "-i",
                str(in_path),
                str(out_part_path),
            ]
            proc = subprocess.run(cmd_fallback, capture_output=True, text=True, check=False)

        if proc.returncode != 0:
            if out_part_path.exists():
                out_part_path.unlink(missing_ok=True)
            stderr_msg = proc.stderr.strip() if proc.stderr else "Unknown error"
            raise AudioError(
                f"FFmpeg split failed for chapter {i} ({out_part_path}):\n{stderr_msg}"
            )

        units.append(
            AudioUnit(
                path=out_part_path,
                start_s=start_s,
                end_s=end_s,
                title=title,
            )
        )

    return units


def to_wav16k(
    path: str | Path,
    out_path: str | Path,
) -> Path:
    """Downsample and convert audio to 16 kHz mono PCM WAV for alignment.

    Executes ``ffmpeg -i in -ac 1 -ar 16000 out.wav``.
    """
    in_path = Path(path)
    if not in_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # Caching: skip conversion if valid WAV already exists
    if out_file.is_file() and out_file.stat().st_size > 0:
        log.info("Using cached 16kHz WAV: %s", out_file)
        return out_file

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise AudioError("ffmpeg is not installed or not found on PATH")

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(in_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(out_file),
    ]

    log.debug("Converting to 16kHz WAV: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if proc.returncode != 0:
        if out_file.exists():
            out_file.unlink(missing_ok=True)
        stderr_msg = proc.stderr.strip() if proc.stderr else "Unknown error"
        raise AudioError(
            f"FFmpeg conversion to 16kHz WAV failed for {in_path}:\n{stderr_msg}"
        )

    return out_file


def prepare_audio_units(
    audio: Union[str, Path, Sequence[Union[str, Path]]],
    work_dir: str | Path | None = None,
) -> list[AudioUnit]:
    """High-level pipeline utility to probe and split audio files into AudioUnits.

    Handles single-file audiobooks with multiple chapters, single-chapter files,
    or multi-file audiobooks.
    """
    audio_paths = [Path(p) for p in audio] if isinstance(audio, (list, tuple)) else [Path(audio)]
    all_units: list[AudioUnit] = []

    for path in audio_paths:
        chapters = probe_chapters(path)
        if len(chapters) > 1:
            split_dir = Path(work_dir) / path.stem if work_dir else path.parent / f"{path.stem}_parts"
            units = split_audio(path, chapters, split_dir)
            all_units.extend(units)
        else:
            ch = chapters[0]
            all_units.append(
                AudioUnit(
                    path=path,
                    start_s=ch.start_s,
                    end_s=ch.end_s,
                    title=ch.title,
                )
            )

    return all_units
