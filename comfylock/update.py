"""`update` - refresh pinned commits / model hashes / parameters in place.

Selectively bumps a lock to the current environment without a full re-pack:

* ``--nodes``  re-reads each git custom node's current HEAD commit.
* ``--models`` re-hashes each model on disk and updates size + hashes.
* ``--params`` re-scans the referenced workflow file's parameters (best effort).

With no selector, all three run. Returns the list of human-readable changes so
``--dry-run`` can preview them.
"""

from __future__ import annotations

import copy
from pathlib import Path

from . import serialize
from .hashes import HashCache
from .model import Hash, Lockfile
from .scan import head_commit, locate_models, relpath, scan_custom_nodes
from .workflow import extract_params


def update_lock(
    lock: Lockfile,
    comfyui_root: str | Path,
    do_nodes: bool = True,
    do_models: bool = True,
    do_params: bool = True,
    workflow_path: str | Path | None = None,
    cache: HashCache | None = None,
) -> tuple[Lockfile, list[str]]:
    root = Path(comfyui_root)
    cache = cache or HashCache()
    new = copy.deepcopy(lock)
    changes: list[str] = []

    if do_nodes and new.git_nodes:
        scanned, _ = scan_custom_nodes(root)
        # Match scanned nodes back to locked URLs and bump the commit if changed.
        for url in list(new.git_nodes):
            current = scanned.get(url)
            if current is None:
                # Try matching the node directory by URL last segment.
                node_dir = root / "custom_nodes" / _node_name(url)
                current = head_commit(node_dir) if node_dir.exists() else None
            if current and current != new.git_nodes[url]:
                changes.append(
                    f"node {_node_name(url)}: {new.git_nodes[url][:10]} -> {current[:10]}"
                )
                new.git_nodes[url] = current

    if do_models and new.models:
        located = locate_models(root, [m.name for m in new.models])
        for m in new.models:
            path = located.found.get(m.name)
            if path is None or not path.exists():
                continue
            new_size = path.stat().st_size
            if m.size is not None and new_size != m.size:
                changes.append(f"model {m.name}: size {m.size} -> {new_size}")
            m.size = new_size
            m.paths = [relpath(root, path)]
            types = [h.type for h in m.hashes] or ["SHA256"]
            new_hashes = []
            for t in types:
                try:
                    value = cache.get(path, t)
                except Exception:
                    continue
                old = m.hash_of(t)
                if old and old != value:
                    changes.append(f"model {m.name}: {t} {old[:10]} -> {value[:10]}")
                new_hashes.append(Hash(type=t, hash=value))
            m.hashes = new_hashes
            m.present = True

    if do_params:
        wf = Path(workflow_path) if workflow_path else _find_workflow(lock, root)
        if wf and wf.exists():
            try:
                workflow = serialize.read_workflow(wf)
                params = extract_params(workflow)
                if params != new.parameters:
                    changes.append("parameters updated from workflow")
                    new.parameters = params
            except (RuntimeError, OSError):
                pass

    cache.save()
    return new, changes


def _find_workflow(lock: Lockfile, root: Path) -> Path | None:
    if not lock.workflow:
        return None
    for cand in (Path(lock.workflow), root / lock.workflow, Path.cwd() / lock.workflow):
        if cand.exists():
            return cand
    return None


def _node_name(url: str) -> str:
    seg = url.rstrip("/").replace("\\", "/").rstrip("/").split("/")[-1]
    return seg[:-4] if seg.endswith(".git") else seg


def write_update(new: Lockfile, out_path: str | Path, backup: bool = True) -> Path:
    """Write the updated lock, backing up an overwritten target to ``*.bak``."""
    out = Path(out_path)
    if backup and out.exists():
        bak = out.with_suffix(out.suffix + ".bak")
        bak.write_bytes(out.read_bytes())
    return serialize.write(new, out)
