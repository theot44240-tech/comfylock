"""`verify` - check that the current environment matches a lockfile."""

from __future__ import annotations

from pathlib import Path

from .hashes import COMPUTABLE, HashCache
from .model import SCHEMA_VERSION, Lockfile, Model
from .report import Report
from .scan import (
    LocatedModels,
    head_commit,
    is_git_repo,
    locate_models,
    relpath,
    scan_comfyui_commit,
)


def _verifiable_hash(model: Model) -> tuple[str, str] | None:
    """Pick a (type, value) from the model's hashes that we can recompute."""
    for ht in COMPUTABLE:
        v = model.hash_of(ht)
        if v:
            return ht, v
    return None


def verify(
    lock: Lockfile,
    comfyui_root: str | Path | None,
    check_hashes: bool = True,
    cache: HashCache | None = None,
) -> Report:
    report = Report()
    cache = cache or HashCache()
    root = Path(comfyui_root) if comfyui_root is not None else None

    # --- Schema compatibility ---
    if lock.version > SCHEMA_VERSION:
        report.warn(
            f"Lockfile schema v{lock.version} is newer than this tool "
            f"(v{SCHEMA_VERSION}); some checks may be skipped. Upgrade comfylock."
        )

    # --- ComfyUI core commit ---
    if lock.comfyui:
        actual = scan_comfyui_commit(root) if root else None
        if actual is None:
            report.warn(f"ComfyUI: cannot read commit (locked {lock.comfyui[:10]}).")
        elif actual == lock.comfyui:
            report.ok(f"ComfyUI: commit {actual[:10]} matches.")
        else:
            report.error(
                f"ComfyUI: commit {actual[:10]} != locked {lock.comfyui[:10]}."
            )

    # --- Git custom nodes ---
    for url, commit in sorted(lock.git_nodes.items()):
        node_dir = _node_dir_for(root, url) if root else None
        if node_dir is None or not node_dir.exists():
            report.error(f"Node missing: {url} (need {commit[:10]}).")
            continue
        if not is_git_repo(node_dir):
            report.warn(f"Node not a git repo: {node_dir.name} ({url}).")
            continue
        actual = head_commit(node_dir)
        if actual == commit:
            report.ok(f"Node {node_dir.name}: {commit[:10]} matches.")
        else:
            short = actual[:10] if actual else "?"
            report.error(f"Node {node_dir.name}: {short} != locked {commit[:10]}.")

    # --- File custom nodes ---
    for fn in lock.file_nodes:
        path = (root / "custom_nodes" / fn.filename) if root else None
        disabled_path = (
            (root / "custom_nodes" / (fn.filename + ".disabled")) if root else None
        )
        present = bool(path and path.exists()) or bool(
            disabled_path and disabled_path.exists()
        )
        if present:
            report.ok(f"File node present: {fn.filename}.")
        else:
            report.error(f"File node missing: {fn.filename}.")

    # --- Models ---
    located = (
        locate_models(root, [m.name for m in lock.models])
        if root
        else LocatedModels({}, {})
    )
    for m in lock.models:
        if not m.present:
            report.warn(f"Model '{m.name}': not pinned (was missing at pack time).")
            continue
        path = located.found.get(m.name)
        if path is None and m.paths and root:
            cand = root / m.paths[0]
            path = cand if cand.exists() else None
        if path is None or not path.exists():
            report.error(f"Model '{m.name}': file not found.")
            continue
        if m.name in located.ambiguous and root:
            others = ", ".join(
                relpath(root, p) for p in located.ambiguous[m.name] if p != path
            )
            report.warn(
                f"Model '{m.name}': basename matches several files "
                f"(verifying {relpath(root, path)}; also: {others})."
            )
        if m.size is not None and path.stat().st_size != m.size:
            report.error(
                f"Model '{m.name}': size {path.stat().st_size} != locked {m.size}."
            )
            continue
        if not check_hashes:
            report.ok(f"Model '{m.name}': present (hash check skipped).")
            continue
        hv = _verifiable_hash(m)
        if hv is None:
            report.warn(f"Model '{m.name}': no recomputable hash in lock.")
            continue
        ht, expected = hv
        actual = cache.get(path, ht)
        if actual == expected:
            report.ok(f"Model '{m.name}': {ht} matches.")
        else:
            report.error(
                f"Model '{m.name}': expected {ht}={expected[:12]}.. "
                f"but got {actual[:12]}.. (re-download?)."
            )
    cache.save()
    return report


def _node_dir_for(root: Path, url: str):
    """Best-effort: map a repo URL to its custom_nodes/<name> directory."""
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return root / "custom_nodes" / name
