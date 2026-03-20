from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _configure_local_runtime_dirs() -> None:
    project_root = Path(__file__).resolve().parent
    runtime_root = project_root / "test-artifacts" / "runtime"
    mpl_config_dir = project_root / ".cache" / "matplotlib"

    runtime_root.mkdir(parents=True, exist_ok=True)
    mpl_config_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("TMPDIR", str(runtime_root))
    os.environ.setdefault("TEMP", str(runtime_root))
    os.environ.setdefault("TMP", str(runtime_root))
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_config_dir))

    tempfile.tempdir = str(runtime_root)


_configure_local_runtime_dirs()
