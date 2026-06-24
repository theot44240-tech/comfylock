"""`manager-import` - build a ComfyLock lockfile from a ComfyUI-Manager snapshot.

Inverse of ``export --format manager-snapshot``. A CM snapshot pins the ComfyUI
commit and custom nodes but carries no model information, so the resulting lock
has no model hashes (a warning is emitted to that effect).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import __version__, serialize
from .exporters.manager_snapshot import from_manager_snapshot


def manager_import(
    snapshot_path: str | Path,
    out_path: str | Path | None = None,
    comfyui_root: str | Path | None = None,
) -> tuple[Path, list[str]]:
    p = Path(snapshot_path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"snapshot not found: {p}") from exc
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"{p}: not a UTF-8 text snapshot ({exc}).") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{p}: invalid snapshot JSON: {exc}") from exc

    lock, warnings = from_manager_snapshot(data)
    lock.comfylock_version = __version__
    lock.workflow = p.stem

    if out_path is None:
        out_path = p.with_suffix(".lock")
    out = serialize.write(lock, out_path)
    return out, warnings
