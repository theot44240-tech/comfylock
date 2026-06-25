"""``doctor`` -- diagnose a ComfyUI install and (optionally) a lockfile.

Pure filesystem + PATH inspection (stdlib only). Returns a :class:`report.Report`
of ok/warn/error checks, each carrying an actionable suggestion so a user knows
not just *what* failed but *what to do about it*.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import serialize
from .model import SCHEMA_VERSION
from .report import Report

# Subdirectories a typical ComfyUI install keeps under ``models/``. A missing one
# is only a warning -- ``unpack`` creates them on demand -- but their absence is a
# useful hint that the root is empty or mis-pointed.
MODEL_SUBDIRS = ("checkpoints", "loras", "vae", "controlnet", "clip", "unet")


def _check_root(rep: Report, root: str | None) -> None:
    if not root:
        rep.warn("no --comfyui-root given: skipping install checks (pass -r PATH)")
        return
    base = Path(root)
    if not base.exists():
        rep.error(f"ComfyUI root not found: {root} (pass a valid -r/--comfyui-root)")
        return
    if (base / "main.py").exists() or (base / "server.py").exists():
        rep.ok(f"ComfyUI entrypoint present in {root}")
    else:
        rep.error(
            f"no main.py/server.py under {root}: this may not be a ComfyUI install"
        )
    for sub in ("models", "custom_nodes"):
        if (base / sub).is_dir():
            rep.ok(f"{sub}/ directory present")
        else:
            rep.error(f"{sub}/ missing under {root}: create it or fix the root path")
    models = base / "models"
    if models.is_dir():
        missing = [s for s in MODEL_SUBDIRS if not (models / s).is_dir()]
        if missing:
            rep.warn(
                "model subdirs missing: "
                + ", ".join(missing)
                + " (created automatically on unpack)"
            )
        else:
            rep.ok("standard model subdirectories present")


def _check_git(rep: Report) -> None:
    if shutil.which("git"):
        rep.ok("git found on PATH")
    else:
        rep.error("git not on PATH: node pinning and unpack need git -- install it")


def _check_locks(rep: Report, root: str | None) -> None:
    seen: set[Path] = set()
    found: list[Path] = []
    for d in [Path("."), Path(root) if root else None]:
        if d is None or not d.is_dir():
            continue
        for lock in sorted(d.glob("*.lock")):
            r = lock.resolve()
            if r not in seen:
                seen.add(r)
                found.append(lock)
    if found:
        rep.ok(f"found {len(found)} lockfile(s): " + ", ".join(p.name for p in found))
    else:
        rep.warn("no .lock files found nearby: run `comfy-lock pack <workflow>`")


def _check_lock(rep: Report, lock_path: str) -> None:
    try:
        lock = serialize.read(lock_path)
    except (RuntimeError, OSError, FileNotFoundError) as exc:
        rep.error(f"cannot read {lock_path}: {exc}")
        return
    if lock.version > SCHEMA_VERSION:
        rep.warn(
            f"lock schema v{lock.version} is newer than this tool (v{SCHEMA_VERSION}): "
            "upgrade comfylock to read all fields"
        )
    else:
        rep.ok(f"lock schema v{lock.version} is readable")
    if not lock.models:
        rep.warn(f"{lock_path} pins zero models: nothing to verify/unpack")
    else:
        no_url = sum(1 for m in lock.models if not m.url)
        if no_url:
            rep.warn(
                f"{no_url}/{len(lock.models)} model(s) have no download URL: "
                "unpack cannot fetch them (add a url or place them manually)"
            )
        else:
            rep.ok(f"{len(lock.models)} model(s) all have a download URL")


def _check_cache(rep: Report, root: str | None) -> None:
    base = Path(root) if root else Path(".")
    cache = base / ".comfylock-cache.json"
    if not cache.exists():
        return  # absence is fine -- it is created on first hash
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        rep.warn(f"{cache} is not valid JSON: safe to delete (it will be rebuilt)")
        return
    if isinstance(data, dict):
        rep.ok("hash cache present and valid")
    else:
        rep.warn(f"{cache} is not a JSON object: safe to delete")


def doctor(comfyui_root: str | None = None, lock_path: str | None = None) -> Report:
    rep = Report()
    _check_root(rep, comfyui_root)
    _check_git(rep)
    _check_locks(rep, comfyui_root)
    if lock_path:
        _check_lock(rep, lock_path)
    _check_cache(rep, comfyui_root)
    return rep
