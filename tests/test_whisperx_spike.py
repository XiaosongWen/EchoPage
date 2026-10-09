import sys
import subprocess
from pathlib import Path
import pytest


def test_spike_script_help():
    """Verify scripts/whisperx_spike.py runs --help successfully."""
    script_path = Path(__file__).parent.parent / "scripts" / "whisperx_spike.py"
    assert script_path.exists(), "scripts/whisperx_spike.py must exist"

    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Run WhisperX transcription and forced alignment spike" in result.stdout
    assert "--device" in result.stdout
    assert "--compute-type" in result.stdout


def test_spike_script_missing_audio(tmp_path):
    """Verify scripts/whisperx_spike.py exits with error when audio is not found."""
    script_path = Path(__file__).parent.parent / "scripts" / "whisperx_spike.py"
    non_existent = tmp_path / "non_existent.wav"

    result = subprocess.run(
        [sys.executable, str(script_path), "--audio", str(non_existent)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Error: audio file not found" in result.stderr


def test_optional_extra_align_installed():
    """Verify whisperx and torch are importable when [align] extra is installed."""
    import importlib.util

    whisperx_spec = importlib.util.find_spec("whisperx")
    torch_spec = importlib.util.find_spec("torch")
    assert whisperx_spec is not None, "whisperx should be installed with [align] extra"
    assert torch_spec is not None, "torch should be installed with [align] extra"
