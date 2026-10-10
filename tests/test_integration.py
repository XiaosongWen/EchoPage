"""End-to-end integration tests for EchoPage build pipeline (Task 14)."""

import shutil
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from echopage.cli import main
from echopage.alignment import load_alignment


@pytest.fixture
def build_workspace(tmp_path: Path):
    """Set up workspace with fixture EPUB and audio parts."""
    fixtures_dir = Path("tests/fixtures")
    epub_src = fixtures_dir / "book.epub"
    audio_parts = sorted((fixtures_dir / "book_parts").glob("*.m4b"))

    work_dir = tmp_path / "work"
    out_epub = tmp_path / "dist" / "narrated.epub"
    out_epub.parent.mkdir(parents=True, exist_ok=True)

    return {
        "epub": epub_src,
        "audio": audio_parts,
        "work_dir": work_dir,
        "out_epub": out_epub,
    }


def test_end_to_end_build_from_fixtures(build_workspace: dict, monkeypatch):
    """Test full build pipeline produces a valid EPUB with Media Overlays."""
    sample_alignment = load_alignment(Path("tests/fixtures/alignment.sample.json"))
    # Mock aligner.align to return sample alignment for instant execution
    monkeypatch.setattr("echopage.aligner.align", lambda *a, **kw: sample_alignment)

    args = [
        "build",
        "--epub", str(build_workspace["epub"]),
        "--audio", *[str(p) for p in build_workspace["audio"]],
        "--output", str(build_workspace["out_epub"]),
        "--work-dir", str(build_workspace["work_dir"]),
    ]

    exit_code = main(args)
    assert exit_code == 0
    assert build_workspace["out_epub"].is_file()

    # Verify EPUB internal structure
    with zipfile.ZipFile(build_workspace["out_epub"], "r") as zf:
        names = zf.namelist()
        assert names[0] == "mimetype"
        assert zf.read("mimetype") == b"application/epub+zip"
        assert "META-INF/container.xml" in names
        assert "EPUB/package.opf" in names
        assert any(n.endswith(".smil") for n in names)
        assert any(n.startswith("EPUB/audio/") for n in names)


def test_build_caching_and_force(build_workspace: dict, monkeypatch, capsys: pytest.CaptureFixture):
    """Test that a second run with same work_dir reuses cached alignment unless --force is given."""
    sample_alignment = load_alignment(Path("tests/fixtures/alignment.sample.json"))

    align_calls = []

    def mock_align(*a, **kw):
        align_calls.append(True)
        return sample_alignment

    monkeypatch.setattr("echopage.aligner.align", mock_align)

    base_args = [
        "build",
        "--epub", str(build_workspace["epub"]),
        "--audio", *[str(p) for p in build_workspace["audio"]],
        "--output", str(build_workspace["out_epub"]),
        "--work-dir", str(build_workspace["work_dir"]),
    ]

    # First run: should call align
    ret1 = main(base_args)
    assert ret1 == 0
    assert len(align_calls) == 1
    assert (build_workspace["work_dir"] / "alignment.json").is_file()

    # Second run without --force: should reuse cached alignment without calling aligner.align
    ret2 = main(base_args)
    assert ret2 == 0
    assert len(align_calls) == 1  # Not called again!

    # Third run with --force: should call aligner.align again
    ret3 = main(base_args + ["--force"])
    assert ret3 == 0
    assert len(align_calls) == 2


def test_keep_temp_cleans_up_scratch_wavs(build_workspace: dict, monkeypatch):
    """Test Review #7: scratch WAVs are deleted when --keep-temp is omitted, preserved when set."""
    sample_alignment = load_alignment(Path("tests/fixtures/alignment.sample.json"))

    def mock_align(*a, **kw):
        # Simulate creating scratch WAV directory
        wav_dir = build_workspace["work_dir"] / "wav16k"
        wav_dir.mkdir(parents=True, exist_ok=True)
        (wav_dir / "temp.wav").write_bytes(b"wav")
        return sample_alignment

    monkeypatch.setattr("echopage.aligner.align", mock_align)

    # Run without --keep-temp: scratch WAV dir should be cleaned up
    main([
        "build",
        "--epub", str(build_workspace["epub"]),
        "--audio", *[str(p) for p in build_workspace["audio"]],
        "--output", str(build_workspace["out_epub"]),
        "--work-dir", str(build_workspace["work_dir"]),
        "--force",
    ])
    assert not (build_workspace["work_dir"] / "wav16k").exists()

    # Run with --keep-temp: scratch WAV dir should be kept
    main([
        "build",
        "--epub", str(build_workspace["epub"]),
        "--audio", *[str(p) for p in build_workspace["audio"]],
        "--output", str(build_workspace["out_epub"]),
        "--work-dir", str(build_workspace["work_dir"]),
        "--keep-temp",
        "--force",
    ])
    assert (build_workspace["work_dir"] / "wav16k").exists()


def test_phase_failure_reports_phase_and_hint(build_workspace: dict, monkeypatch, capsys: pytest.CaptureFixture):
    """Test that build failure in a phase logs the phase name and actionable fix hint."""
    def fail_parse(*a, **kw):
        raise ValueError("Simulated corrupt EPUB parse error")

    monkeypatch.setattr("echopage.parser.parse", fail_parse)

    args = [
        "build",
        "--epub", str(build_workspace["epub"]),
        "--audio", *[str(p) for p in build_workspace["audio"]],
        "--output", str(build_workspace["out_epub"]),
        "--work-dir", str(build_workspace["work_dir"]),
    ]

    ret = main(args)
    assert ret == 1
    captured = capsys.readouterr()
    assert "Build failed in phase 'parse'" in captured.out
    assert "Fix hint (parse)" in captured.out


def test_granularity_word_not_supported_error(build_workspace: dict, capsys: pytest.CaptureFixture):
    """Test --granularity word gives clean error message without crash traceback."""
    args = [
        "build",
        "--epub", str(build_workspace["epub"]),
        "--audio", *[str(p) for p in build_workspace["audio"]],
        "--output", str(build_workspace["out_epub"]),
        "--granularity", "word",
    ]

    ret = main(args)
    assert ret == 1
    captured = capsys.readouterr()
    assert "Granularity 'word' is not yet supported" in captured.out
