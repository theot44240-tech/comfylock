"""Render a lockfile's git custom nodes as a ``requirements-comfy.txt``.

Each git-backed node becomes a ``git+https://...@<commit>`` line. ComfyUI custom
nodes are not pip packages, so this is informational (not directly installable),
but it documents the exact node set and plugs into tooling that reads
requirements-style files.
"""

from __future__ import annotations

from .. import __version__
from ..model import Lockfile


def to_requirements(lock: Lockfile) -> str:
    out: list[str] = [
        f"# ComfyLock {__version__} -- custom node pins "
        "(informational; not pip-installable)"
    ]
    if lock.workflow:
        out.append(f"# workflow: {lock.workflow}")
    if not lock.git_nodes:
        out.append("# (no git-backed custom nodes in this lock)")
    for url, commit in sorted(lock.git_nodes.items()):
        clean = url[:-4] if url.endswith(".git") else url
        out.append(f"git+{clean}@{commit}")
    return "\n".join(out) + "\n"
