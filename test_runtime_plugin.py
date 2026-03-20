from __future__ import annotations

import os
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
RUNTIME_ROOT = PROJECT_ROOT / "test-artifacts" / "runtime"
MPLCONFIGDIR = PROJECT_ROOT / ".cache" / "matplotlib"

RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
MPLCONFIGDIR.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("TMPDIR", str(RUNTIME_ROOT))
os.environ.setdefault("TEMP", str(RUNTIME_ROOT))
os.environ.setdefault("TMP", str(RUNTIME_ROOT))
os.environ.setdefault("MPLCONFIGDIR", str(MPLCONFIGDIR))
tempfile.tempdir = str(RUNTIME_ROOT)


def pytest_configure() -> None:
    if os.name == "nt":
        import _pytest.pathlib as pytest_pathlib
        import _pytest.tmpdir as pytest_tmpdir

        original_cleanup_dead_symlinks = pytest_pathlib.cleanup_dead_symlinks
        original_rm_rf = pytest_pathlib.rm_rf
        original_getbasetemp = pytest_tmpdir.TempPathFactory.getbasetemp

        def _safe_cleanup_dead_symlinks(root: Path) -> None:
            try:
                original_cleanup_dead_symlinks(root)
            except PermissionError:
                return

        def _safe_rm_rf(path: Path) -> None:
            try:
                original_rm_rf(path)
            except PermissionError:
                return

        def _safe_getbasetemp(self: pytest_tmpdir.TempPathFactory) -> Path:
            try:
                return original_getbasetemp(self)
            except PermissionError:
                fallback = RUNTIME_ROOT / "pytest-fallback"
                fallback.mkdir(parents=True, exist_ok=True)
                self._basetemp = fallback
                return fallback

        pytest_pathlib.cleanup_dead_symlinks = _safe_cleanup_dead_symlinks
        pytest_tmpdir.cleanup_dead_symlinks = _safe_cleanup_dead_symlinks
        pytest_pathlib.rm_rf = _safe_rm_rf
        pytest_tmpdir.rm_rf = _safe_rm_rf
        pytest_tmpdir.TempPathFactory.getbasetemp = _safe_getbasetemp
