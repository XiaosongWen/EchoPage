"""Tests for echopage.audio module."""

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from echopage.audio import (
    AudioError,
    AudioUnit,
    ChapterDict,
    parse_chapters_json,
    prepare_audio_units,
    probe_chapters,
    split_audio,
    to_wav16k,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Canned ffprobe JSON Unit Tests
# ---------------------------------------------------------------------------

def test_parse_chapters_json_with_explicit_timestamps():
    """Verify chapter parsing from canned ffprobe JSON with start_time and end_time."""
    canned = {
        "chapters": [
            {
                "id": 0,
                "time_base": "1/1000",
                "start": 0,
                "start_time": "0.000000",
                "end": 12500,
                "end_time": "12.500000",
                "tags": {"title": "Introduction"},
            },
            {
                "id": 1,
                "time_base": "1/1000",
                "start": 12500,
                "start_time": "12.500000",
                "end": 35200,
                "end_time": "35.200000",
                "tags": {"title": "Chapter 1"},
            },
        ]
    }
    result = parse_chapters_json(canned)
    assert len(result) == 2
    assert result[0]["title"] == "Introduction"
    assert result[0]["start_s"] == pytest.approx(0.0)
    assert result[0]["end_s"] == pytest.approx(12.5)

    assert result[1]["title"] == "Chapter 1"
    assert result[1]["start_s"] == pytest.approx(12.5)
    assert result[1]["end_s"] == pytest.approx(35.2)

    # Test attribute access on ChapterDict
    assert result[0].title == "Introduction"
    assert result[0].start_s == pytest.approx(0.0)
    assert result[0].end_s == pytest.approx(12.5)


def test_parse_chapters_json_from_json_string():
    """Verify string JSON is accepted directly."""
    canned_str = json.dumps({
        "chapters": [
            {
                "id": 0,
                "start_time": "1.234",
                "end_time": "5.678",
                "tags": {"title": "Prologue"},
            }
        ]
    })
    result = parse_chapters_json(canned_str)
    assert len(result) == 1
    assert result[0]["title"] == "Prologue"
    assert result[0]["start_s"] == pytest.approx(1.234)
    assert result[0]["end_s"] == pytest.approx(5.678)


def test_parse_chapters_json_missing_time_strings_uses_ticks_and_time_base():
    """Verify fallback to ticks and time_base when start_time/end_time are omitted."""
    canned = {
        "chapters": [
            {
                "id": 0,
                "time_base": "1/1000",
                "start": 5000,
                "end": 15000,
            }
        ]
    }
    result = parse_chapters_json(canned)
    assert len(result) == 1
    assert result[0]["title"] == "Chapter 1"
    assert result[0]["start_s"] == pytest.approx(5.0)
    assert result[0]["end_s"] == pytest.approx(15.0)


def test_parse_chapters_json_missing_titles_generates_defaults():
    """Verify fallback titles 'Chapter 1', 'Chapter 2' when title tags are absent."""
    canned = {
        "chapters": [
            {"id": 0, "start_time": "0.0", "end_time": "10.0"},
            {"id": 1, "start_time": "10.0", "end_time": "20.0"},
        ]
    }
    result = parse_chapters_json(canned)
    assert result[0]["title"] == "Chapter 1"
    assert result[1]["title"] == "Chapter 2"


def test_parse_chapters_json_no_chapters_yields_one_unit():
    """Verify file without chapters yields 1 unit spanning total duration."""
    canned = {
        "chapters": [],
        "format": {
            "duration": "42.500000",
            "tags": {"title": "Single File Audiobook"},
        },
    }
    result = parse_chapters_json(canned)
    assert len(result) == 1
    assert result[0]["title"] == "Single File Audiobook"
    assert result[0]["start_s"] == pytest.approx(0.0)
    assert result[0]["end_s"] == pytest.approx(42.5)


def test_parse_chapters_json_no_chapters_fallback_duration():
    """Verify fallback duration and title when format duration/title are absent."""
    canned = {"chapters": []}
    result = parse_chapters_json(canned, fallback_duration=99.9, fallback_title="Fallback Title")
    assert len(result) == 1
    assert result[0]["title"] == "Fallback Title"
    assert result[0]["start_s"] == pytest.approx(0.0)
    assert result[0]["end_s"] == pytest.approx(99.9)


def test_parse_chapters_json_invalid_inputs():
    """Verify error handling on invalid JSON or invalid types."""
    with pytest.raises(AudioError, match="Failed to parse ffprobe JSON"):
        parse_chapters_json("not valid json {")
    with pytest.raises(TypeError):
        parse_chapters_json(12345)


# ---------------------------------------------------------------------------
# AudioUnit Class Unit Tests
# ---------------------------------------------------------------------------

def test_audio_unit_properties_and_access():
    """Verify AudioUnit dataclass behaviour, unpacking, and item access."""
    p = Path("/tmp/part_0.m4b")
    unit = AudioUnit(path=p, start_s=0.0, end_s=23.833, title="Chapter 1")

    assert unit.path == p
    assert unit.start_s == pytest.approx(0.0)
    assert unit.end_s == pytest.approx(23.833)
    assert unit.title == "Chapter 1"
    assert unit.duration == pytest.approx(23.833)

    # Tuple unpacking
    path_val, start_val, end_val, title_val = unit
    assert path_val == p
    assert start_val == pytest.approx(0.0)
    assert end_val == pytest.approx(23.833)
    assert title_val == "Chapter 1"

    # Indexing by integer and key
    assert unit[0] == p
    assert unit[1] == pytest.approx(0.0)
    assert unit["title"] == "Chapter 1"
    assert unit["path"] == p

    with pytest.raises(KeyError):
        _ = unit["nonexistent"]


# ---------------------------------------------------------------------------
# Acceptance Criteria: Real Fixtures Probing & Splitting
# ---------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not installed")
def test_probe_chapters_fixture_two_chapters():
    """Acceptance Criteria 1: The fixture file with 2 chapters yields 2 units

    with correct start/end times (within 0.1 s).
    """
    m4b_path = FIXTURES_DIR / "book.m4b"
    assert m4b_path.exists()

    chapters = probe_chapters(m4b_path)
    assert len(chapters) == 2, f"Expected 2 chapters, found {len(chapters)}"

    ch1 = chapters[0]
    ch2 = chapters[1]

    # Chapter 1: ~0.0s to ~23.833s
    assert abs(ch1["start_s"] - 0.0) <= 0.1
    assert abs(ch1["end_s"] - 23.833) <= 0.1
    assert "Tortoise" in ch1["title"]

    # Chapter 2: ~23.833s to ~45.159s
    assert abs(ch2["start_s"] - 23.833) <= 0.1
    assert abs(ch2["end_s"] - 45.159) <= 0.1
    assert "North Wind" in ch2["title"]


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not installed")
def test_probe_chapters_fixture_no_chapters():
    """Acceptance Criteria 2: A file without chapters yields 1 unit."""
    mp3_path = FIXTURES_DIR / "book.mp3"
    assert mp3_path.exists()

    chapters = probe_chapters(mp3_path)
    assert len(chapters) == 1, f"Expected 1 unit, found {len(chapters)}"

    unit = chapters[0]
    assert abs(unit["start_s"] - 0.0) <= 0.1
    assert abs(unit["end_s"] - 45.228) <= 0.1


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="ffmpeg/ffprobe not installed")
def test_split_audio_fixture_duration_and_units(tmp_path):
    """Acceptance Criteria 1, 4: Split 2-chapter fixture into AudioUnits and

    verify total duration is within 0.5 s of source duration.
    """
    m4b_path = FIXTURES_DIR / "book.m4b"
    chapters = probe_chapters(m4b_path)
    assert len(chapters) == 2

    units = split_audio(m4b_path, chapters, out_dir=tmp_path)
    assert len(units) == 2

    # Verify returned AudioUnit start/end timestamps within 0.1s
    assert abs(units[0].start_s - 0.0) <= 0.1
    assert abs(units[0].end_s - 23.833) <= 0.1
    assert "Tortoise" in units[0].title

    assert abs(units[1].start_s - 23.833) <= 0.1
    assert abs(units[1].end_s - 45.159) <= 0.1
    assert "North Wind" in units[1].title

    # Verify split output files exist
    assert units[0].path.is_file() and units[0].path.stat().st_size > 0
    assert units[1].path.is_file() and units[1].path.stat().st_size > 0

    # Probe duration of split parts via ffprobe
    durations = []
    for u in units:
        res = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                str(u.path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        info = json.loads(res.stdout)
        durations.append(float(info["format"]["duration"]))

    split_total = sum(durations)

    # Get source duration
    src_res = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(m4b_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    src_duration = float(json.loads(src_res.stdout)["format"]["duration"])

    # Acceptance Criteria 4: total duration within 0.5 s
    diff = abs(split_total - src_duration)
    assert diff <= 0.5, f"Split duration difference {diff}s exceeds 0.5s tolerance"


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="ffmpeg/ffprobe not installed")
def test_to_wav16k_fixture_properties(tmp_path):
    """Acceptance Criteria 3: The WAV output reports 16000 Hz, 1 channel via ffprobe."""
    m4b_path = FIXTURES_DIR / "book.m4b"
    wav_out = tmp_path / "test_16k.wav"

    res_path = to_wav16k(m4b_path, wav_out)
    assert res_path == wav_out
    assert wav_out.is_file() and wav_out.stat().st_size > 0

    # Verify format via ffprobe
    res = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,sample_rate,channels",
            "-of", "json",
            str(wav_out),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(res.stdout)
    assert "streams" in data and len(data["streams"]) > 0
    stream = data["streams"][0]

    assert stream["codec_name"] == "pcm_s16le"
    assert int(stream["sample_rate"]) == 16000
    assert int(stream["channels"]) == 1


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="ffmpeg/ffprobe not installed")
def test_split_audio_caching(tmp_path):
    """Verify split_audio reuses existing files in out_dir without re-running ffmpeg."""
    m4b_path = FIXTURES_DIR / "book.m4b"
    chapters = probe_chapters(m4b_path)

    # First run generates files
    units1 = split_audio(m4b_path, chapters, out_dir=tmp_path)
    part0_mtime = units1[0].path.stat().st_mtime_ns

    # Second run should reuse files
    units2 = split_audio(m4b_path, chapters, out_dir=tmp_path)
    part0_mtime_after = units2[0].path.stat().st_mtime_ns

    assert part0_mtime == part0_mtime_after
    assert len(units2) == 2


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="ffmpeg/ffprobe not installed")
def test_to_wav16k_caching(tmp_path):
    """Verify to_wav16k reuses existing WAV file."""
    m4b_path = FIXTURES_DIR / "book.m4b"
    wav_out = tmp_path / "cached.wav"

    to_wav16k(m4b_path, wav_out)
    mtime1 = wav_out.stat().st_mtime_ns

    to_wav16k(m4b_path, wav_out)
    mtime2 = wav_out.stat().st_mtime_ns

    assert mtime1 == mtime2


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="ffmpeg/ffprobe not installed")
def test_prepare_audio_units_high_level(tmp_path):
    """Verify prepare_audio_units handles multi-chapter container and single files."""
    m4b_path = FIXTURES_DIR / "book.m4b"
    units_m4b = prepare_audio_units(m4b_path, work_dir=tmp_path)
    assert len(units_m4b) == 2

    ch1_path = FIXTURES_DIR / "ch01.mp3"
    ch2_path = FIXTURES_DIR / "ch02.mp3"
    units_multi = prepare_audio_units([ch1_path, ch2_path], work_dir=tmp_path)
    assert len(units_multi) == 2
    assert units_multi[0].path == ch1_path
    assert units_multi[1].path == ch2_path


# ---------------------------------------------------------------------------
# Error Handling & Subprocess Edge Cases
# ---------------------------------------------------------------------------

def test_missing_input_file_errors():
    """Verify FileNotFoundError is raised when input file is not found."""
    nonexistent = Path("/nonexistent/audio.m4b")
    with pytest.raises(FileNotFoundError):
        probe_chapters(nonexistent)
    with pytest.raises(FileNotFoundError):
        split_audio(nonexistent)
    with pytest.raises(FileNotFoundError):
        to_wav16k(nonexistent, "/tmp/out.wav")


def test_missing_binaries_raise_audio_error(monkeypatch):
    """Verify AudioError is raised when ffprobe or ffmpeg is missing."""
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    m4b_path = FIXTURES_DIR / "book.m4b"

    with pytest.raises(AudioError, match="ffprobe is not installed"):
        probe_chapters(m4b_path)
    with pytest.raises(AudioError, match="ffmpeg is not installed"):
        split_audio(m4b_path, [{"title": "t", "start_s": 0, "end_s": 10}], "/tmp")
    with pytest.raises(AudioError, match="ffmpeg is not installed"):
        to_wav16k(m4b_path, "/tmp/out.wav")


def test_ffmpeg_split_failure_raises_audio_error(monkeypatch, tmp_path):
    """Verify AudioError captures stderr when ffmpeg split command fails."""
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/ffmpeg")

    mock_fail = MagicMock(returncode=1, stderr="Invalid data found when processing input")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_fail)

    m4b_path = FIXTURES_DIR / "book.m4b"
    with pytest.raises(AudioError, match="FFmpeg split failed"):
        split_audio(m4b_path, [{"title": "c1", "start_s": 0, "end_s": 5}], out_dir=tmp_path)


def test_ffmpeg_to_wav16k_failure_raises_audio_error(monkeypatch, tmp_path):
    """Verify AudioError captures stderr when ffmpeg wav conversion fails."""
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/ffmpeg")

    mock_fail = MagicMock(returncode=1, stderr="Conversion error")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_fail)

    m4b_path = FIXTURES_DIR / "book.m4b"
    with pytest.raises(AudioError, match="FFmpeg conversion to 16kHz WAV failed"):
        to_wav16k(m4b_path, tmp_path / "out.wav")
