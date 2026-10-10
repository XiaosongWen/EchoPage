"""Unit and integration tests for EPUB container packaging and validation (Task 13)."""

import shutil
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from echopage import packager
from echopage.packager import (
    EpubCheckValidationError,
    PackagerError,
    validate_epubcheck,
    zip_epub,
)


@pytest.fixture
def temp_epub_dir(tmp_path: Path) -> Path:
    """Create a temporary populated EPUB directory ready for packaging."""
    fixture_dir = Path("tests/fixtures/.echopage_unpack_book")
    work = tmp_path / "work"
    shutil.copytree(fixture_dir, work)

    # Add a mock audio file
    audio_dir = work / "EPUB" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "chapter01.mp3").write_bytes(b"mock-mp3-bytes")

    # Add stray files that should be ignored
    (work / ".DS_Store").write_bytes(b"garbage")
    (work / "EPUB" / ".DS_Store").write_bytes(b"garbage")
    (work / "EPUB" / "styles.css~").write_text("backup", encoding="utf-8")
    (work / "temp.tmp").write_text("temp", encoding="utf-8")
    pycache = work / "__pycache__"
    pycache.mkdir()
    (pycache / "foo.pyc").write_bytes(b"byte-code")

    return work


def test_zip_epub_mimetype_is_first_and_stored(temp_epub_dir: Path, tmp_path: Path):
    """Test Acceptance Criterion 1: unzip -v shows mimetype first with method Stored."""
    out_epub = tmp_path / "book.epub"
    res = zip_epub(temp_epub_dir, out_epub)
    assert res == out_epub
    assert out_epub.is_file()

    with zipfile.ZipFile(out_epub, "r") as zf:
        infos = zf.infolist()
        assert len(infos) > 0
        first_entry = infos[0]
        assert first_entry.filename == "mimetype"
        assert first_entry.compress_type == zipfile.ZIP_STORED


def test_zip_epub_mimetype_exact_content(temp_epub_dir: Path, tmp_path: Path):
    """Test Acceptance Criterion 2: The mimetype content is exact application/epub+zip without newline."""
    out_epub = tmp_path / "book.epub"
    zip_epub(temp_epub_dir, out_epub)

    with zipfile.ZipFile(out_epub, "r") as zf:
        content = zf.read("mimetype")
        assert content == b"application/epub+zip"
        assert not content.endswith(b"\n")
        assert not content.endswith(b"\r")


def test_zip_epub_compression_modes(temp_epub_dir: Path, tmp_path: Path):
    """Test that audio files use ZIP_STORED and text/XML files use ZIP_DEFLATED."""
    out_epub = tmp_path / "book.epub"
    zip_epub(temp_epub_dir, out_epub)

    with zipfile.ZipFile(out_epub, "r") as zf:
        info_map = {info.filename: info.compress_type for info in zf.infolist()}
        assert info_map["mimetype"] == zipfile.ZIP_STORED
        assert info_map["EPUB/audio/chapter01.mp3"] == zipfile.ZIP_STORED
        assert info_map["META-INF/container.xml"] == zipfile.ZIP_DEFLATED
        assert info_map["EPUB/package.opf"] == zipfile.ZIP_DEFLATED
        assert info_map["EPUB/chapter01.xhtml"] == zipfile.ZIP_DEFLATED


def test_zip_epub_no_stray_files(temp_epub_dir: Path, tmp_path: Path):
    """Test Acceptance Criterion 5: Output contains no stray files (.DS_Store, temp files)."""
    out_epub = tmp_path / "book.epub"
    zip_epub(temp_epub_dir, out_epub)

    with zipfile.ZipFile(out_epub, "r") as zf:
        names = zf.namelist()
        for name in names:
            assert ".DS_Store" not in name
            assert not name.endswith("~")
            assert not name.endswith(".tmp")
            assert "__pycache__" not in name
            assert not Path(name).name.startswith(".")


def test_validate_epubcheck_missing_returns_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """Test Acceptance Criterion 4: A missing EPUBCheck gives a warning, not a crash."""
    epub_file = tmp_path / "dummy.epub"
    epub_file.write_bytes(b"data")

    with patch("shutil.which", return_value=None):
        valid, msg = validate_epubcheck(epub_file)
        assert valid is True
        assert "skipped" in msg.lower()
        assert any("not installed" in record.message for record in caplog.records)


def test_validate_epubcheck_success(tmp_path: Path):
    """Test successful EPUBCheck execution."""
    epub_file = tmp_path / "dummy.epub"
    epub_file.write_bytes(b"data")

    mock_proc = MagicMock(returncode=0, stdout="No errors or warnings detected", stderr="")
    with patch("shutil.which", return_value="/usr/local/bin/epubcheck"), \
         patch("subprocess.run", return_value=mock_proc):
        valid, report = validate_epubcheck(epub_file)
        assert valid is True
        assert "No errors" in report


def test_validate_epubcheck_failure(tmp_path: Path):
    """Test EPUBCheck execution with validation errors."""
    epub_file = tmp_path / "dummy.epub"
    epub_file.write_bytes(b"data")

    mock_proc = MagicMock(returncode=1, stdout="ERROR(RSC-005): Error in package", stderr="")
    with patch("shutil.which", return_value="/usr/local/bin/epubcheck"), \
         patch("subprocess.run", return_value=mock_proc):
        valid, report = validate_epubcheck(epub_file)
        assert valid is False
        assert "ERROR(RSC-005)" in report


def test_package_pipeline_creates_real_epub(tmp_path: Path):
    """Test package() produces an actual valid EPUB archive."""
    work_dir = tmp_path / "work"
    shutil.copytree("tests/fixtures/.echopage_unpack_book", work_dir)

    alignment_file = Path("tests/fixtures/alignment.sample.json")
    audio_parts = sorted(Path("tests/fixtures/book_parts").glob("*.m4b"))
    output_epub = tmp_path / "dist" / "output.epub"

    res = packager.package(
        epub=Path("tests/fixtures/book.epub"),
        audio=audio_parts,
        alignment=alignment_file,
        output=output_epub,
        work_dir=work_dir,
        validate_epub=False,
    )

    assert res == output_epub
    assert output_epub.is_file()
    assert output_epub.stat().st_size > 1000

    # Verify inside of created EPUB
    with zipfile.ZipFile(output_epub, "r") as zf:
        names = zf.namelist()
        assert names[0] == "mimetype"
        assert "META-INF/container.xml" in names
        assert "EPUB/package.opf" in names
        assert any(n.endswith(".smil") for n in names)
        assert any("audio/" in n for n in names)


def test_package_pipeline_without_work_dir(tmp_path: Path):
    """Test package() creates output even when work_dir is None (auto temp directory)."""
    alignment_file = Path("tests/fixtures/alignment.sample.json")
    audio_parts = sorted(Path("tests/fixtures/book_parts").glob("*.m4b"))
    output_epub = tmp_path / "auto_work_output.epub"

    res = packager.package(
        epub=Path("tests/fixtures/book.epub"),
        audio=audio_parts,
        alignment=alignment_file,
        output=output_epub,
        work_dir=None,
        validate_epub=False,
    )

    assert res == output_epub
    assert output_epub.is_file()
    with zipfile.ZipFile(output_epub, "r") as zf:
        assert zf.namelist()[0] == "mimetype"
