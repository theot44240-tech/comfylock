"""`merge` - combine several workflow locks into one environment lock.

Custom nodes are unioned (keyed by repo URL / filename); models are unioned
(keyed by canonical name). A *conflict* is the same key pinned to two different
commits/hashes:

* ``strategy="first"`` keeps the earliest lock's pin and warns.
* ``strategy="strict"`` raises with the full conflict list.

Parameters are intentionally dropped: distinct workflows have unrelated
parameter sets that would only collide.
"""

from __future__ import annotations

from . import __version__
from .model import FileNode, Lockfile, Model

STRATEGIES = ("first", "strict")


class MergeConflict(RuntimeError):
    """Raised under ``strategy="strict"`` when two locks pin the same item apart."""


def _model_fingerprint(m: Model) -> str:
    """A content fingerprint: the strongest hash if any, else size, else url."""
    for h in m.hashes:
        if h.type.upper() in ("SHA256", "BLAKE3", "BLAKE2B"):
            return f"{h.type.upper()}:{h.hash}"
    if m.hashes:
        return f"{m.hashes[0].type.upper()}:{m.hashes[0].hash}"
    if m.size is not None:
        return f"size:{m.size}"
    return f"url:{m.url or ''}"


def merge_locks(locks: list[Lockfile], strategy: str = "first") -> tuple[Lockfile, list[str]]:
    if strategy not in STRATEGIES:
        raise RuntimeError(f"Unknown strategy {strategy!r}. Valid: {', '.join(STRATEGIES)}.")
    if not locks:
        raise RuntimeError("merge needs at least one lock.")

    warnings: list[str] = []
    conflicts: list[str] = []

    git_nodes: dict[str, str] = {}
    for lock in locks:
        for url, commit in lock.git_nodes.items():
            if url in git_nodes and git_nodes[url] != commit:
                msg = f"node {url}: {git_nodes[url][:10]} vs {commit[:10]}"
                conflicts.append(msg)
                warnings.append(f"conflict ({msg}); kept {git_nodes[url][:10]}")
                continue
            git_nodes.setdefault(url, commit)

    file_nodes: dict[str, FileNode] = {}
    for lock in locks:
        for fn in lock.file_nodes:
            file_nodes.setdefault(fn.filename, fn)

    models: dict[str, Model] = {}
    for lock in locks:
        for m in lock.models:
            if m.name in models:
                if _model_fingerprint(models[m.name]) != _model_fingerprint(m):
                    msg = f"model {m.name}: differing content"
                    conflicts.append(msg)
                    warnings.append(f"conflict ({msg}); kept the first")
                continue
            models[m.name] = m

    comfyui_commits = {lock.comfyui for lock in locks if lock.comfyui}
    comfyui = None
    if len(comfyui_commits) == 1:
        comfyui = next(iter(comfyui_commits))
    elif len(comfyui_commits) > 1:
        msg = "ComfyUI core: " + " vs ".join(sorted(c[:10] for c in comfyui_commits))
        conflicts.append(msg)
        comfyui = locks[0].comfyui
        warnings.append(f"conflict ({msg}); kept {comfyui[:10] if comfyui else '?'}")

    if strategy == "strict" and conflicts:
        raise MergeConflict(
            "merge --strategy strict found "
            f"{len(conflicts)} conflict(s):\n  - " + "\n  - ".join(conflicts)
        )

    merged = Lockfile(
        comfyui=comfyui,
        git_nodes=git_nodes,
        file_nodes=list(file_nodes.values()),
        models=list(models.values()),
        comfylock_version=__version__,
    )
    return merged, warnings
