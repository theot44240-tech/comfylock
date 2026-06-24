"""Convert between a ComfyLock lockfile and a ComfyUI-Manager snapshot.

ComfyUI-Manager's ``snapshot.json`` pins the ComfyUI commit and custom nodes but
does not track models. This module is the bridge in both directions:

* :func:`to_manager_snapshot` — emit a CM-compatible snapshot from a lock.
* :func:`from_manager_snapshot` — build a lock from a CM snapshot (see the
  ``manager-import`` command, which can additionally hash on-disk models).
"""

from __future__ import annotations

import json
from typing import Any

from ..model import FileNode, Lockfile


def to_manager_snapshot(lock: Lockfile) -> str:
    git_nodes: dict[str, Any] = {
        url: {"hash": commit, "disabled": False}
        for url, commit in sorted(lock.git_nodes.items())
    }
    file_nodes = [
        {"filename": fn.filename, "disabled": fn.disabled}
        for fn in sorted(lock.file_nodes, key=lambda f: f.filename)
    ]
    snap: dict[str, Any] = {
        "comfyui": lock.comfyui or "",
        "git_custom_nodes": git_nodes,
        "file_custom_nodes": file_nodes,
        "pips": {},
    }
    return json.dumps(snap, indent=2, ensure_ascii=False) + "\n"


def from_manager_snapshot(data: Any) -> tuple[Lockfile, list[str]]:
    """Build a Lockfile from a parsed CM snapshot dict.

    Returns ``(lock, warnings)``. Tolerates a malformed/partial snapshot the same
    way the lock model tolerates untrusted input: bad types degrade to empty.
    """
    warnings: list[str] = []
    if not isinstance(data, dict):
        raise RuntimeError("snapshot is not a JSON object.")

    comfyui = data.get("comfyui")
    git_nodes: dict[str, str] = {}
    raw_git = data.get("git_custom_nodes")
    if isinstance(raw_git, dict):
        for url, info in raw_git.items():
            commit = ""
            if isinstance(info, dict):
                commit = str(info.get("hash", ""))
            elif isinstance(info, str):
                commit = info
            git_nodes[str(url)] = commit

    file_nodes: list[FileNode] = []
    raw_files = data.get("file_custom_nodes")
    if isinstance(raw_files, list):
        for fn in raw_files:
            if isinstance(fn, dict) and fn.get("filename"):
                file_nodes.append(
                    FileNode(
                        filename=str(fn["filename"]),
                        disabled=bool(fn.get("disabled", False)),
                    )
                )

    lock = Lockfile(
        comfyui=str(comfyui) if isinstance(comfyui, str) and comfyui else None,
        git_nodes=git_nodes,
        file_nodes=file_nodes,
    )
    warnings.append(
        "ComfyUI-Manager snapshots do not track models; the imported lock has no "
        "model hashes. Re-run with -r <ComfyUI root> to hash models on disk."
    )
    return lock, warnings
