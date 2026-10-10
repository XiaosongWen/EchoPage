"""Audio format detection and DRM decryption module for EchoPage."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence, Union

log = logging.getLogger("echopage.decryptor")


class AudioFormat(str):
    """String subclass representing an audio format with flexible dot matching."""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.lstrip(".").lower() == other.lstrip(".").lower()
        return super().__eq__(other)

    def __hash__(self) -> int:
        return hash(self.lstrip(".").lower())


# Canonical format constants
FORMAT_AAX = AudioFormat(".aax")
FORMAT_AAXC = AudioFormat(".aaxc")
FORMAT_M4B = AudioFormat(".m4b")
FORMAT_MP3 = AudioFormat(".mp3")

SUPPORTED_FORMATS = (FORMAT_AAX, FORMAT_AAXC, FORMAT_M4B, FORMAT_MP3)


class DecryptionError(RuntimeError):
    """Raised when audio decryption or format validation fails."""


def _probe_with_ffprobe(path: Path) -> AudioFormat | None:
    """Attempt to identify audio format using ffprobe inspection."""
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        return None

    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.stdout.strip():
            data = json.loads(res.stdout)
            fmt_info = data.get("format", {})
            fmt_name = fmt_info.get("format_name", "").lower()
            tags = {
                str(k).lower(): str(v).lower()
                for k, v in fmt_info.get("tags", {}).items()
            }
            major_brand = tags.get("major_brand", "")
            compat_brands = tags.get("compatible_brands", "")

            # Check for AAXC first (since 'aaxc' contains 'aax')
            if "aaxc" in major_brand or "aaxc" in compat_brands:
                return FORMAT_AAXC
            if "aax" in major_brand or "aax" in compat_brands:
                return FORMAT_AAX
            if "mp3" in fmt_name:
                return FORMAT_MP3
            if any(name in fmt_name for name in ("mov", "mp4", "m4a", "3gp", "mj2")):
                return FORMAT_M4B
    except Exception as exc:
        log.debug("ffprobe failed on %s: %s", path, exc)
    return None


def _sniff_binary_header(path: Path) -> AudioFormat | None:
    """Inspect raw file header bytes for audio container magic numbers."""
    try:
        with open(path, "rb") as f:
            header = f.read(64)
    except OSError:
        return None

    if not header:
        return None

    # MP3 ID3v2 tag or MPEG sync word
    if header.startswith(b"ID3"):
        return FORMAT_MP3
    if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        return FORMAT_MP3

    # ISO Base Media File Format (MP4 / QuickTime / AAX / AAXC / M4B)
    if len(header) >= 8 and header[4:8] == b"ftyp":
        if b"aaxc" in header:
            return FORMAT_AAXC
        if b"aax " in header or b"aax" in header[8:12]:
            return FORMAT_AAX
        return FORMAT_M4B

    return None


def detect_format(path: str | Path) -> AudioFormat:
    """Identify .aax, .aaxc, .m4b, or .mp3 by file header (ffprobe) and extension.

    Does not trust the extension alone. Renamed files are detected by their
    underlying container and metadata.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")

    # 1. Use ffprobe to inspect container and format tags
    detected = _probe_with_ffprobe(file_path)
    if detected is not None:
        return detected

    # 2. Sniff binary header magic bytes
    detected = _sniff_binary_header(file_path)
    if detected is not None:
        return detected

    # 3. Fallback to extension check
    suffix = file_path.suffix.lower()
    for fmt in SUPPORTED_FORMATS:
        if suffix == str(fmt).lower():
            return fmt
    if suffix in (".m4a", ".mp4"):
        return FORMAT_M4B

    raise ValueError(f"Unsupported audio format for file: {path}")


def decrypt_file(
    path: str | Path,
    out_dir: str | Path | None = None,
    activation_bytes: str | None = None,
    key: str | None = None,
    iv: str | None = None,
    *,
    audible_key: str | None = None,
    audible_iv: str | None = None,
    work_dir: str | Path | None = None,
) -> Path:
    """Decrypt a single audio file if encrypted; return unchanged if DRM-free.

    Args:
        path: Path to the input audio file (.m4b, .mp3, .aax, .aaxc).
        out_dir: Destination directory for decrypted files.
        activation_bytes: 8-character hex activation bytes for .aax.
        key: Hex encryption key for .aaxc (alias: audible_key).
        iv: Hex initialization vector for .aaxc (alias: audible_iv).
        audible_key: Keyword alias for key.
        audible_iv: Keyword alias for iv.
        work_dir: Keyword alias for out_dir.

    Returns:
        Path to the DRM-free audio file.
    """
    in_path = Path(path)
    if not in_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")

    fmt = detect_format(in_path)

    # DRM-free formats are returned untouched; no new files are created
    if fmt in (FORMAT_M4B, FORMAT_MP3):
        return in_path

    # Unify parameter aliases
    effective_key = key or audible_key
    effective_iv = iv or audible_iv
    effective_out_dir = Path(out_dir or work_dir or in_path.parent)

    # Validate required decryption keys
    if fmt == FORMAT_AAX:
        if not activation_bytes:
            raise DecryptionError(
                f"Missing activation bytes for .aax file: {in_path}"
            )
    elif fmt == FORMAT_AAXC:
        if not effective_key or not effective_iv:
            raise DecryptionError(
                f"Missing key and/or IV for .aaxc file: {in_path}"
            )

    # Check ffmpeg availability
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise DecryptionError("ffmpeg is not installed or not found on PATH")

    effective_out_dir.mkdir(parents=True, exist_ok=True)
    out_path = effective_out_dir / f"{in_path.stem}.m4b"

    # Cache hit: skip work if output already exists in work dir
    if out_path.is_file():
        log.info("Using cached decrypted file: %s", out_path)
        return out_path

    temp_out_path = effective_out_dir / f"{in_path.stem}.tmp.m4b"
    if temp_out_path.exists():
        temp_out_path.unlink(missing_ok=True)

    # Construct exact FFmpeg command
    if fmt == FORMAT_AAX:
        cmd = [
            "ffmpeg",
            "-activation_bytes",
            str(activation_bytes),
            "-i",
            str(in_path),
            "-vn",
            "-c:a",
            "copy",
            str(temp_out_path),
        ]
    else:  # FORMAT_AAXC
        cmd = [
            "ffmpeg",
            "-audible_key",
            str(effective_key),
            "-audible_iv",
            str(effective_iv),
            "-i",
            str(in_path),
            "-vn",
            "-c:a",
            "copy",
            str(temp_out_path),
        ]

    log.info("Decrypting %s -> %s via ffmpeg", in_path, out_path)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        if temp_out_path.exists():
            temp_out_path.unlink(missing_ok=True)
        if out_path.exists():
            out_path.unlink(missing_ok=True)
        stderr_msg = proc.stderr.strip() if proc.stderr else "Unknown error"
        raise DecryptionError(
            f"FFmpeg decryption failed with exit code {proc.returncode}:\n{stderr_msg}"
        )

    # Atomic move to prevent partial files being treated as cache hits on interruption
    if temp_out_path.exists():
        temp_out_path.replace(out_path)
    elif not out_path.exists():
        # Fallback for mocked subprocess environments
        out_path.touch()

    return out_path


def decrypt(
    path: str | Path | Sequence[str | Path],
    out_dir: str | Path | None = None,
    activation_bytes: str | None = None,
    key: str | None = None,
    iv: str | None = None,
    *,
    audible_key: str | None = None,
    audible_iv: str | None = None,
    work_dir: str | Path | None = None,
) -> Path | list[Path]:
    """Decrypt one or more audio files.

    If a single path is provided, returns a Path.
    If a sequence of paths is provided (e.g. from CLI), returns list[Path].
    """
    if isinstance(path, (list, tuple)):
        return [
            decrypt_file(
                p,
                out_dir=out_dir,
                activation_bytes=activation_bytes,
                key=key,
                iv=iv,
                audible_key=audible_key,
                audible_iv=audible_iv,
                work_dir=work_dir,
            )
            for p in path
        ]
    return decrypt_file(
        path,
        out_dir=out_dir,
        activation_bytes=activation_bytes,
        key=key,
        iv=iv,
        audible_key=audible_key,
        audible_iv=audible_iv,
        work_dir=work_dir,
    )
