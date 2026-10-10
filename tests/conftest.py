"""Pytest fixtures and test suite configuration for EchoPage."""

import shutil
from pathlib import Path
import pytest


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_artifacts():
    """Ensure test-generated artifacts for fixture books do not linger,
    without touching user builds or workspace directories.
    """
    root_dir = Path(__file__).resolve().parent.parent

    # Restrict cleanup strictly to test-generated fixtures
    test_artifact_patterns = (
        ".echopage_build_book*",
        ".echopage_build_sample*",
        "dummy*.epub",
    )

    def _purge_artifacts():
        for pattern in test_artifact_patterns:
            for p in root_dir.glob(pattern):
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                elif p.is_file():
                    p.unlink(missing_ok=True)

    # Clean before test session starts
    _purge_artifacts()
    yield
    # Clean after test session finishes
    _purge_artifacts()
