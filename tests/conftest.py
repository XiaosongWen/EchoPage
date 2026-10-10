"""Pytest fixtures and test suite configuration for EchoPage."""

import shutil
from pathlib import Path
import pytest


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_artifacts():
    """Ensure no test-generated build or unpack directories linger in workspace root."""
    root_dir = Path(__file__).resolve().parent.parent

    def _purge_artifacts():
        # Clean any .echopage_build_* or .echopage_unpack_* created in repo root
        for pattern in (".echopage_build_*", ".echopage_unpack_*"):
            for p in root_dir.glob(pattern):
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                elif p.is_file():
                    p.unlink(missing_ok=True)
        # Also clean any dummy.epub or test epubs left at root
        for dummy in root_dir.glob("dummy*.epub"):
            dummy.unlink(missing_ok=True)

    # Clean before test session starts
    _purge_artifacts()
    yield
    # Clean after test session finishes
    _purge_artifacts()
