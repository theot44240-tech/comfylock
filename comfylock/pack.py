"""`pack` - build a lockfile from a workflow + the current ComfyUI environment."""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import platform
import socket
from pathlib import Path
from typing import Any

from . import __version__, serialize
from .hashes import COMPUTABLE, HashCache
from .model import HASH_TYPES, SCHEMA_VERSION, Hash, Lockfile, Model
from .scan import (
    locate_models,
    relpath,
    scan_comfyui_commit,
    scan_custom_nodes,
)
from .workflow import extract_models, extract_params


class StrictError(RuntimeError):
    """Raised by ``pack --strict`` when a referenced model is missing on disk."""


def _provenance() -> dict[str, Any]:
    """Best-effort author/machine metadata for a v2 lock (opt-in).

    The hostname is stored as a SHA256 digest by default so the lock can be
    shared without leaking the machine name. Off by default because it makes
    a pack non-reproducible across machines.
    """
    host = socket.gethostname() or ""
    prov: dict[str, Any] = {
        "hostname": hashlib.sha256(host.encode("utf-8")).hexdigest()[:16] if host else None,
        "os": platform.system().lower() or None,
        "python": platform.python_version(),
    }
    author = os.environ.get("COMFYLOCK_AUTHOR") or os.environ.get("USER") or os.environ.get(
        "USERNAME"
    )
    if author:
        prov["author"] = author
    return {k: v for k, v in prov.items() if v is not None}


def _now_iso() -> str:
    """UTC timestamp, honouring ``SOURCE_DATE_EPOCH`` for reproducible builds.

    When ``SOURCE_DATE_EPOCH`` is set to a valid Unix time, two packs of the same
    environment produce byte-identical lockfiles (useful in CI / diffing).
    """
    sde = os.environ.get("SOURCE_DATE_EPOCH")
    if sde:
        # A non-numeric or out-of-range value must not crash pack: int() rejects
        # garbage, and fromtimestamp() raises OverflowError/OSError/ValueError for
        # an epoch outside the platform's representable range (e.g. a huge or very
        # negative number). Fall through to "now" in every such case.
        try:
            ts = int(sde)
            return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_hash_types(hash_types: list[str] | None) -> list[str]:
    """Validate requested hash types, returning canonical names.

    Unknown types and known-but-unavailable types (e.g. BLAKE3 without the
    optional package) raise a clear error instead of silently producing a
    lockfile hashed with a different algorithm than the user asked for.
    """
    if not hash_types:
        return ["SHA256"]
    computable = {h.upper(): h for h in COMPUTABLE}
    known = {h.upper() for h in HASH_TYPES}
    resolved: list[str] = []
    for h in hash_types:
        key = h.upper()
        if key in computable:
            canon = computable[key]
            if canon not in resolved:
                resolved.append(canon)
        elif key in known:
            raise RuntimeError(
                f"Hash type {h!r} is not available in this environment. "
                "Install its optional dependency (e.g. `pip install comfylock[blake3]`)."
            )
        else:
            raise RuntimeError(
                f"Unknown hash type {h!r}. Valid types: {', '.join(COMPUTABLE)}."
            )
    return resolved


def build_lock(
    workflow: Any,
    workflow_name: str | None,
    comfyui_root: str | Path | None,
    hash_types: list[str] | None = None,
    cache: HashCache | None = None,
    lock_version: int = SCHEMA_VERSION,
    strict: bool = False,
    provenance: bool = False,
) -> Lockfile:
    """Construct a Lockfile in memory. Pure-ish: only reads the filesystem.

    ``lock_version`` selects the on-disk schema (2 by default; pass 1 for a
    v1-compatible lock). ``strict`` raises :class:`StrictError` if any model the
    workflow references is absent on disk. ``provenance`` records opt-in
    author/machine metadata (v2 only).
    """
    hash_types = _resolve_hash_types(hash_types)
    cache = cache or HashCache()

    model_names = extract_models(workflow)
    params = extract_params(workflow)

    lock = Lockfile(
        workflow=workflow_name,
        generated=_now_iso(),
        parameters=params,
        version=lock_version,
    )
    if lock_version >= 2:
        lock.comfylock_version = __version__
        if provenance:
            lock.provenance = _provenance()

    found: dict[str, Path] = {}
    if comfyui_root is not None:
        lock.comfyui = scan_comfyui_commit(comfyui_root)
        lock.git_nodes, lock.file_nodes = scan_custom_nodes(comfyui_root)
        found = locate_models(comfyui_root, model_names).found

    missing: list[str] = []
    for name in model_names:
        m = Model(name=name)
        path = found.get(name)
        if path is not None and path.exists():
            m.present = True
            m.size = path.stat().st_size
            m.paths = [relpath(comfyui_root, path)] if comfyui_root else [str(path)]
            for ht in hash_types:
                m.hashes.append(Hash(type=ht, hash=cache.get(path, ht)))
        else:
            m.present = False
            missing.append(name)
        lock.models.append(m)

    cache.save()
    if strict and missing:
        raise StrictError(
            f"{len(missing)} model(s) referenced by the workflow are missing on disk: "
            + ", ".join(sorted(missing))
        )
    return lock


def pack(
    workflow_path: str | Path,
    out_path: str | Path | None = None,
    comfyui_root: str | Path | None = None,
    hash_types: list[str] | None = None,
    cache_path: str | Path | None = None,
    lock_version: int = SCHEMA_VERSION,
    strict: bool = False,
    provenance: bool = False,
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
        lock_version=lock_version,
        strict=strict,
        provenance=provenance,
    )
    return serialize.write(lock, out_path)
