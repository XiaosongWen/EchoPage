import shutil
from pathlib import Path

import pytest

from echopage.cli import main


@pytest.fixture
def files(tmp_path, monkeypatch):
    epub = tmp_path / "b.epub"
    audio = tmp_path / "a.m4b"
    shutil.copy(Path(__file__).parent / "fixtures" / "book.epub", epub)
    audio.write_bytes(b"x")
    monkeypatch.setattr("echopage.aligner.align", lambda *a, **kw: [])
    return ["build", "--epub", str(epub), "--audio", str(audio),
            "--output", str(tmp_path / "out.epub"),
            "--work-dir", str(tmp_path / "work")]


def test_valid_runs_four_phases(files, capsys):
    assert main(files) == 0
    out = capsys.readouterr().out
    for phase in ("decrypt", "parse", "align", "package"):
        assert f"{phase}: start" in out and f"{phase}: done" in out


def test_missing_file(files, capsys):
    files[2] = "/nonexistent.epub"
    with pytest.raises(SystemExit) as e:
        main(files)
    assert e.value.code != 0
    assert "file not found" in capsys.readouterr().err


def test_bad_activation_bytes(files, capsys):
    with pytest.raises(SystemExit) as e:
        main(files + ["--activation-bytes", "xyz"])
    assert e.value.code != 0
    assert "8 hex" in capsys.readouterr().err


def test_good_activation_bytes(files):
    assert main(files + ["--activation-bytes", "1a2B3c4D"]) == 0


def test_key_iv_together(files):
    with pytest.raises(SystemExit):
        main(files + ["--audible-key", "aa"])
    assert main(files + ["--audible-key", "aa", "--audible-iv", "bb"]) == 0


def test_help_lists_flags(capsys):
    with pytest.raises(SystemExit) as e:
        main(["build", "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--epub", "--audio", "--output", "--activation-bytes", "--audible-key",
                 "--audible-iv", "--granularity", "--model-size", "--device",
                 "--work-dir", "--verbose"):
        assert flag in out


def test_cli_build_aax_without_activation_bytes(tmp_path, capsys):
    epub = tmp_path / "b.epub"
    epub.write_bytes(b"x")
    aax = Path(__file__).parent / "fixtures" / "sample.aax"
    cmd = ["build", "--epub", str(epub), "--audio", str(aax),
           "--output", str(tmp_path / "out.epub"),
           "--work-dir", str(tmp_path / "work")]
    code = main(cmd)
    assert code != 0
    out = capsys.readouterr().out
    assert "Missing activation bytes" in out


def test_cli_build_aax_with_activation_bytes_succeeds(tmp_path, capsys):
    epub = tmp_path / "b.epub"
    shutil.copy(Path(__file__).parent / "fixtures" / "book.epub", epub)
    aax = Path(__file__).parent / "fixtures" / "sample.aax"
    cmd = ["build", "--epub", str(epub), "--audio", str(aax),
           "--activation-bytes", "1a2b3c4d",
           "--output", str(tmp_path / "out.epub"),
           "--work-dir", str(tmp_path / "work")]
    with pytest.MonkeyPatch.context() as mp:
        from unittest.mock import MagicMock
        mp.setattr("subprocess.run", lambda *a, **kw: MagicMock(returncode=0, stdout="", stderr=""))
        mp.setattr("echopage.aligner.align", lambda *a, **kw: [])
        code = main(cmd)
    assert code == 0
    out = capsys.readouterr().out
    assert "decrypt: start" in out and "decrypt: done" in out


def test_cli_probe_subcommand(capsys):
    fixture = Path(__file__).parent / "fixtures" / "book.m4b"
    code = main(["probe", str(fixture)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Total chapters: 2" in out
    assert "Tortoise and the Hare" in out


def test_cli_split_subcommand(tmp_path, capsys):
    fixture = Path(__file__).parent / "fixtures" / "book.m4b"
    code = main(["split", str(fixture), "--out-dir", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Split" in out
    assert (tmp_path / "part_0.m4b").exists()
    assert (tmp_path / "part_1.m4b").exists()


def test_cli_towav_subcommand(tmp_path, capsys):
    fixture = Path(__file__).parent / "fixtures" / "book.m4b"
    out_wav = tmp_path / "out.wav"
    code = main(["to-wav", str(fixture), str(out_wav)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Converted to 16kHz mono WAV" in out
    assert out_wav.exists()


def test_cli_decrypt_subcommand(tmp_path, capsys):
    fixture = Path(__file__).parent / "fixtures" / "book.mp3"
    code = main(["decrypt", str(fixture), "--out-dir", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Decrypted audio" in out


def test_cli_parse_subcommand(tmp_path, capsys):
    fixture = Path(__file__).parent / "fixtures" / "book.epub"
    code = main(["parse", str(fixture), "--work-dir", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Unpacked EPUB:" in out
    assert "chapter01" in out
    assert "chapter02" in out
    assert "8 sentences" in out
    assert "5 sentences" in out


def test_cli_parse_missing_file(capsys):
    with pytest.raises(SystemExit) as e:
        main(["parse", "missing.epub"])
    assert e.value.code != 0
    assert "file not found" in capsys.readouterr().err


def test_cli_align_missing_file(capsys):
    with pytest.raises(SystemExit) as e:
        main(["align", "missing.epub", "missing.mp3"])
    assert e.value.code != 0
    assert "file not found" in capsys.readouterr().err


def test_cli_align_subcommand(tmp_path, capsys, monkeypatch):
    epub = Path(__file__).parent / "fixtures" / "book.epub"
    audio = Path(__file__).parent / "fixtures" / "book.m4b"
    out_json = tmp_path / "out_align.json"

    fake_timeline = [
        {"element_id": "mo_s_0001", "text": "Sentence 1", "start_ms": 100, "end_ms": 1500, "confidence": 0.95}
    ]
    from echopage.aligner import AlignedChapter, TimelineEntry
    fake_ch = AlignedChapter({
        "spine_item_id": "ch01",
        "xhtml_filename": "ch01.xhtml",
        "audio_filename": "part_0.m4b",
        "timeline": [TimelineEntry(t) for t in fake_timeline],
    })
    monkeypatch.setattr("echopage.aligner.align", lambda *a, **kw: [fake_ch])

    code = main(["align", str(epub), str(audio), "--json-out", str(out_json), "--work-dir", str(tmp_path / "work")])
    assert code == 0
    out = capsys.readouterr().out
    assert "Aligned 1 chapters:" in out
    assert "mo_s_0001" in out
    assert out_json.is_file()


def test_cli_generate_smil_missing_file(capsys):
    with pytest.raises(SystemExit) as e:
        main(["generate-smil", "missing_dir", "missing.json"])
    assert e.value.code != 0
    assert "directory not found" in capsys.readouterr().err


def test_cli_generate_smil_subcommand(tmp_path, capsys):
    from echopage import parser as epub_parser, packager
    epub = Path(__file__).parent / "fixtures" / "book.epub"
    align_file = Path(__file__).parent / "fixtures" / "alignment.sample.json"
    audio_dir = Path(__file__).parent / "fixtures" / "book_parts"

    work_dir = tmp_path / "epub_work"
    epub_parser.unpack(epub, work_dir)
    packager.inject_alignment_spans(work_dir, align_file)

    code = main(["generate-smil", str(work_dir), str(align_file), "--audio", str(audio_dir)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Generated SMIL playlists for 2 chapters:" in out
    assert "chapter01.smil" in out
    assert (work_dir / "EPUB" / "chapter01.smil").is_file()


def test_cli_build_dry_run(capsys, tmp_path):
    epub = Path(__file__).parent / "fixtures" / "book.epub"
    audio = Path(__file__).parent / "fixtures" / "book.m4b"
    out_file = tmp_path / "out.epub"

    code = main(["build", "--epub", str(epub), "--audio", str(audio), "--output", str(out_file), "--dry-run", "--work-dir", str(tmp_path / "work")])
    assert code == 0
    out = capsys.readouterr().out
    assert "Dry run: planned chapter-to-audio mapping:" in out
    assert "chapter01" in out
    assert "chapter02" in out
    assert not out_file.exists()


def test_cli_build_skip_spine(capsys, tmp_path):
    epub = Path(__file__).parent / "fixtures" / "book.epub"
    audio = Path(__file__).parent / "fixtures" / "chapter02.mp3"
    out_file = tmp_path / "out.epub"

    code = main([
        "build",
        "--epub", str(epub),
        "--audio", str(audio),
        "--output", str(out_file),
        "--skip-spine", "chapter01",
        "--dry-run",
        "--work-dir", str(tmp_path / "work"),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "Dry run: planned chapter-to-audio mapping:" in out
    assert "chapter02" in out
    assert "chapter01" not in out


def test_cli_verbose_logger_filtering(tmp_path):
    import logging
    epub = Path(__file__).parent / "fixtures" / "book.epub"
    audio = Path(__file__).parent / "fixtures" / "book.m4b"
    out_file = tmp_path / "out.epub"

    code = main(["build", "--epub", str(epub), "--audio", str(audio), "--output", str(out_file), "--dry-run", "--verbose", "--work-dir", str(tmp_path / "work")])
    assert code == 0
    assert logging.getLogger("torio").level == logging.WARNING
    assert logging.getLogger("matplotlib").level == logging.WARNING
    # urllib3 remains unmuted for telemetry visibility
    assert logging.getLogger("urllib3").level != logging.WARNING


def test_cli_build_dry_run_split_false(monkeypatch, capsys, tmp_path):
    """Verify that --dry-run never invokes physical split_audio (split=False)."""
    epub = Path(__file__).parent / "fixtures" / "book.epub"
    audio = Path(__file__).parent / "fixtures" / "book.m4b"
    out_file = tmp_path / "out.epub"

    def fail_on_split(*a, **kw):
        raise AssertionError("split_audio should NOT be called during --dry-run!")

    monkeypatch.setattr("echopage.audio.split_audio", fail_on_split)

    code = main(["build", "--epub", str(epub), "--audio", str(audio), "--output", str(out_file), "--dry-run", "--work-dir", str(tmp_path / "work")])
    assert code == 0
    out = capsys.readouterr().out
    assert "Dry run: planned chapter-to-audio mapping:" in out


def test_cli_build_default_work_dir_lifecycle(monkeypatch, tmp_path):
    """Verify default .echopage_build_<stem> is purged on successful build and kept with --keep-temp."""
    from echopage.alignment import load_alignment

    fixtures_dir = Path(__file__).parent / "fixtures"
    epub = fixtures_dir / "book.epub"
    audio_parts = sorted((fixtures_dir / "book_parts").glob("*.m4b"))

    sample_alignment = load_alignment(fixtures_dir / "alignment.sample.json")
    monkeypatch.setattr("echopage.aligner.align", lambda *a, **kw: sample_alignment)

    # Change directory to tmp_path so default .echopage_build_book is created inside tmp_path
    monkeypatch.chdir(tmp_path)
    default_work_dir = tmp_path / ".echopage_build_book"

    # 1. Successful build without --keep-temp cleans up default work_dir
    out_epub = tmp_path / "narrated.epub"
    code = main(["build", "--epub", str(epub), "--audio", *[str(p) for p in audio_parts], "--output", str(out_epub)])
    assert code == 0
    assert out_epub.is_file()
    assert not default_work_dir.exists(), "Default work_dir should be deleted after build completion"

    # 2. Build with --keep-temp preserves default work_dir
    out_epub2 = tmp_path / "narrated2.epub"
    code = main(["build", "--epub", str(epub), "--audio", *[str(p) for p in audio_parts], "--output", str(out_epub2), "--keep-temp"])
    assert code == 0
    assert out_epub2.is_file()
    assert default_work_dir.is_dir(), "Default work_dir should be preserved when --keep-temp is set"

    # 3. Dry-run without --keep-temp cleans up default work_dir
    shutil.rmtree(default_work_dir, ignore_errors=True)
    code = main(["build", "--epub", str(epub), "--audio", str(fixtures_dir / "book.m4b"), "--output", str(out_epub), "--dry-run"])
    assert code == 0
    assert not default_work_dir.exists(), "Default work_dir should be deleted after dry-run completion"




