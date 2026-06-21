"""`pack` - build a lockfile from a workflow + the current ComfyUI environment."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from . import serialize
from .hashes import COMPUTABLE, HashCache
from .model import Hash, Lockfile, Model
from .scan import (
    locate_models,
    relpath,
    scan_comfyui_commit,
    scan_custom_nodes,
)
from .workflow import extract_models, extract_params


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_lock(
    workflow: Any,
    workflow_name: str | None,
    comfyui_root: str | Path | None,
    hash_types: list[str] | None = None,
    cache: HashCache | None = None,
) -> Lockfile:
    """Construct a Lockfile in memory. Pure-ish: only reads the filesystem."""
    canonical = {h.upper(): h for h in COMPUTABLE}
    hash_types = [canonical[h.upper()] for h in (hash_types or ["SHA256"]) if h.upper() in canonical]
    if not hash_types:
        hash_types = ["SHA256"]
    cache = cache or HashCache()

    model_names = extract_models(workflow)
    params = extract_params(workflow)

    lock = Lockfile(
        workflow=workflow_name,
        generated=_now_iso(),
        parameters=params,
    )

    if comfyui_root is not None:
        lock.comfyui = scan_comfyui_commit(comfyui_root)
        lock.git_nodes, lock.file_nodes = scan_custom_nodes(comfyui_root)
        located = locate_models(comfyui_root, model_names)
    else:
        located = {}

    for name in model_names:
        m = Model(name=name)
        path = located.get(name)
        if path is not None and path.exists():
            m.present = True
            m.size = path.stat().st_size
            m.paths = [relpath(comfyui_root, path)] if comfyui_root else [str(path)]
            for ht in hash_types:
                m.hashes.append(Hash(type=ht, hash=cache.get(path, ht)))
        else:
            m.present = False
        lock.models.append(m)

    cache.save()
    return lock


def pack(
    workflow_path: str | Path,
    out_path: str | Path | None = None,
    comfyui_root: str | Path | None = None,
    hash_types: list[str] | None = None,
    cache_path: str | Path | None = None,
) -> Path:
    """Read a workflow file, build the lock, and write it. Returns the path."""
    workflow_path = Path(workflow_path)
    workflow = serialize.read_workflow(workflow_path)
    if out_path is None:
        out_path = workflow_path.with_suffix("").with_suffix(".lock")
    cache = HashCache(cache_path) if cache_path else None
    lock = build_lock(
        workflow,
        workflow_name=workflow_path.name,
        comfyui_root=comfyui_root,
        hash_types=hash_types,
        cache=cache,
    )
    return serialize.write(lock, out_path)
