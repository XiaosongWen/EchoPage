import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echopage import decryptor
from echopage.decryptor import (
    FORMAT_AAX,
    FORMAT_AAXC,
    FORMAT_M4B,
    FORMAT_MP3,
    AudioFormat,
    DecryptionError,
    decrypt,
    decrypt_file,
    detect_format,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
BOOK_M4B = FIXTURES_DIR / "book.m4b"
BOOK_MP3 = FIXTURES_DIR / "book.mp3"
SAMPLE_AAX = FIXTURES_DIR / "sample.aax"
SAMPLE_AAXC = FIXTURES_DIR / "sample.aaxc"


def test_audio_format_equality():
    fmt = AudioFormat(".m4b")
    assert fmt == ".m4b"
    assert fmt == "m4b"
    assert fmt == ".M4B"
    assert fmt in (".m4b", ".mp3")
    assert fmt in ("m4b", "mp3")
    assert fmt != ".aax"
    assert fmt != "aax"


def test_detect_format_fixtures():
    assert detect_format(BOOK_M4B) == FORMAT_M4B
    assert detect_format(BOOK_M4B) == "m4b"
    assert detect_format(BOOK_MP3) == FORMAT_MP3
    assert detect_format(BOOK_MP3) == "mp3"
    assert detect_format(SAMPLE_AAX) == FORMAT_AAX
    assert detect_format(SAMPLE_AAX) == "aax"
    assert detect_format(SAMPLE_AAXC) == FORMAT_AAXC
    assert detect_format(SAMPLE_AAXC) == "aaxc"


def test_detect_format_renamed_fixtures(tmp_path):
    # Rename m4b to arbitrary extensions and verify header detection
    m4b_renamed = tmp_path / "book_renamed.unknown"
    shutil.copy(BOOK_M4B, m4b_renamed)
    assert detect_format(m4b_renamed) == FORMAT_M4B

    m4b_as_mp3 = tmp_path / "book_fake.mp3"
    shutil.copy(BOOK_M4B, m4b_as_mp3)
    assert detect_format(m4b_as_mp3) == FORMAT_M4B

    # Rename mp3 to arbitrary extensions
    mp3_renamed = tmp_path / "song_renamed.dat"
    shutil.copy(BOOK_MP3, mp3_renamed)
    assert detect_format(mp3_renamed) == FORMAT_MP3

    mp3_as_m4b = tmp_path / "song_fake.m4b"
    shutil.copy(BOOK_MP3, mp3_as_m4b)
    assert detect_format(mp3_as_m4b) == FORMAT_MP3

    # Rename AAX to .bin or .m4b
    aax_renamed = tmp_path / "audio_aax.bin"
    shutil.copy(SAMPLE_AAX, aax_renamed)
    assert detect_format(aax_renamed) == FORMAT_AAX

    # Rename AAXC to .bin or .m4b
    aaxc_renamed = tmp_path / "audio_aaxc.bin"
    shutil.copy(SAMPLE_AAXC, aaxc_renamed)
    assert detect_format(aaxc_renamed) == FORMAT_AAXC


def test_detect_format_file_not_found():
    with pytest.raises(FileNotFoundError):
        detect_format(Path("/nonexistent/file.m4b"))


def test_detect_format_unsupported_content(tmp_path):
    text_file = tmp_path / "sample.txt"
    text_file.write_text("Hello world")
    with pytest.raises(ValueError) as exc:
        detect_format(text_file)
    assert "Unsupported audio format" in str(exc.value)


def test_drm_free_untouched_no_new_file(tmp_path):
    out_dir = tmp_path / "out"

    # Test M4B input
    res_m4b = decrypt(BOOK_M4B, out_dir=out_dir)
    assert res_m4b == BOOK_M4B
    assert not out_dir.exists() or list(out_dir.iterdir()) == []

    # Test MP3 input
    res_mp3 = decrypt(BOOK_MP3, out_dir=out_dir)
    assert res_mp3 == BOOK_MP3
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


def test_aax_missing_key_error(tmp_path):
    out_dir = tmp_path / "out"
    with pytest.raises(DecryptionError) as exc:
        decrypt(SAMPLE_AAX, out_dir=out_dir, activation_bytes=None)
    assert "Missing activation bytes" in str(exc.value)


def test_aaxc_missing_key_error(tmp_path):
    out_dir = tmp_path / "out"

    # Missing both
    with pytest.raises(DecryptionError) as exc:
        decrypt(SAMPLE_AAXC, out_dir=out_dir, key=None, iv=None)
    assert "Missing key and/or IV" in str(exc.value)

    # Missing IV
    with pytest.raises(DecryptionError) as exc:
        decrypt(SAMPLE_AAXC, out_dir=out_dir, key="1234", iv=None)
    assert "Missing key and/or IV" in str(exc.value)

    # Missing key
    with pytest.raises(DecryptionError) as exc:
        decrypt(SAMPLE_AAXC, out_dir=out_dir, key=None, iv="5678")
    assert "Missing key and/or IV" in str(exc.value)


def test_missing_ffmpeg_error(tmp_path):
    out_dir = tmp_path / "out"
    with patch("shutil.which", return_value=None):
        with pytest.raises(DecryptionError) as exc:
            decrypt(SAMPLE_AAX, out_dir=out_dir, activation_bytes="1a2b3c4d")
        assert "ffmpeg is not installed" in str(exc.value)


def test_mock_subprocess_exact_ffmpeg_command_aax(tmp_path):
    out_dir = tmp_path / "out"
    expected_out = out_dir / "sample.m4b"

    with patch("subprocess.run") as mock_run:
        # Mock successful ffmpeg run
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        res = decrypt(SAMPLE_AAX, out_dir=out_dir, activation_bytes="1a2b3c4d")
        assert res == expected_out

        # Verify the exact ffmpeg command line was called
        ffmpeg_calls = [
            call[0][0]
            for call in mock_run.call_args_list
            if call[0][0][0] == "ffmpeg"
        ]
        assert len(ffmpeg_calls) == 1
        assert ffmpeg_calls[0] == [
            "ffmpeg",
            "-activation_bytes",
            "1a2b3c4d",
            "-i",
            str(SAMPLE_AAX),
            "-vn",
            "-c:a",
            "copy",
            str(expected_out),
        ]


def test_mock_subprocess_exact_ffmpeg_command_aaxc(tmp_path):
    out_dir = tmp_path / "out"
    expected_out = out_dir / "sample.m4b"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        res = decrypt(
            SAMPLE_AAXC,
            out_dir=out_dir,
            key="0123456789abcdef",
            iv="fedcba9876543210",
        )
        assert res == expected_out

        ffmpeg_calls = [
            call[0][0]
            for call in mock_run.call_args_list
            if call[0][0][0] == "ffmpeg"
        ]
        assert len(ffmpeg_calls) == 1
        assert ffmpeg_calls[0] == [
            "ffmpeg",
            "-audible_key",
            "0123456789abcdef",
            "-audible_iv",
            "fedcba9876543210",
            "-i",
            str(SAMPLE_AAXC),
            "-vn",
            "-c:a",
            "copy",
            str(expected_out),
        ]


def test_ffmpeg_nonzero_error_includes_stderr(tmp_path):
    out_dir = tmp_path / "out"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=187, stdout="", stderr="Error: invalid activation bytes checksum"
        )
        with pytest.raises(DecryptionError) as exc:
            decrypt(SAMPLE_AAX, out_dir=out_dir, activation_bytes="1a2b3c4d")
        assert "invalid activation bytes checksum" in str(exc.value)
        assert "187" in str(exc.value)


def test_caching_skips_work(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    cached_file = out_dir / "sample.m4b"
    cached_file.write_bytes(b"already_decrypted_data")

    with patch("subprocess.run") as mock_run:
        res = decrypt(SAMPLE_AAX, out_dir=out_dir, activation_bytes="1a2b3c4d")
        assert res == cached_file
        # ffmpeg shouldn't be executed because cached file exists
        ffmpeg_calls = [
            call[0][0]
            for call in mock_run.call_args_list
            if call[0][0][0] == "ffmpeg"
        ]
        assert len(ffmpeg_calls) == 0


def test_output_keeps_chapter_metadata(tmp_path):
    # Verify that ffmpeg -vn -c:a copy retains all chapter metadata
    out_file = tmp_path / "remuxed.m4b"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(BOOK_M4B),
        "-vn",
        "-c:a",
        "copy",
        str(out_file),
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # Inspect chapters in output with ffprobe
    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_chapters",
        "-of",
        "json",
        str(out_file),
    ]
    res = subprocess.run(probe_cmd, check=True, capture_output=True, text=True)
    data = json.loads(res.stdout)
    chapters = data.get("chapters", [])
    assert len(chapters) == 2
    assert "The Tortoise and the Hare" in chapters[0].get("tags", {}).get("title", "")
    assert "The North Wind and the Sun" in chapters[1].get("tags", {}).get("title", "")
    assert float(chapters[0]["start_time"]) == pytest.approx(0.0, abs=0.01)
    assert float(chapters[0]["end_time"]) == pytest.approx(23.833, abs=0.05)


def test_decrypt_list_of_files(tmp_path):
    out_dir = tmp_path / "out"
    files = [BOOK_M4B, BOOK_MP3]
    res = decrypt(files, out_dir=out_dir)
    assert isinstance(res, list)
    assert len(res) == 2
    assert res[0] == BOOK_M4B
    assert res[1] == BOOK_MP3
