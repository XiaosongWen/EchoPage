import pytest

from echopage.cli import main


@pytest.fixture
def files(tmp_path):
    epub = tmp_path / "b.epub"
    audio = tmp_path / "a.m4b"
    epub.write_bytes(b"x")
    audio.write_bytes(b"x")
    return ["build", "--epub", str(epub), "--audio", str(audio),
            "--output", str(tmp_path / "out.epub")]


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
