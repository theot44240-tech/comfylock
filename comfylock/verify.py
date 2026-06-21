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
    is_within,
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
        # ``url`` is untrusted; ``_node_dir_for`` turns its last path segment
        # into a directory name. On Windows that segment can be a UNC/rooted/
        # drive path (e.g. ``\\attacker\share``) that pathlib treats as absolute,
        # escaping ``custom_nodes`` -- an unconfined ``.exists()`` would then leak
        # NTLM credentials / hang on a remote share (existence oracle + DoS), and
        # ``..`` would probe the root itself. Confine before stat'ing, mirroring
        # the model-path and file-node guards. (``unpack`` confines the same way.)
        node_dir = _node_dir_for(root, url) if root is not None else None
        if (
            root is None
            or node_dir is None
            or not is_within(root, node_dir)
            or not node_dir.exists()
        ):
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
        # ``fn.filename`` is untrusted; confine it under the root before stat'ing.
        # An absolute or ``../`` filename would otherwise turn the present/missing
        # report into a file-existence oracle, and ``.exists()`` on a device/UNC
        # path can hang or leak credentials. Mirrors the model-path guard above.
        # (``unpack`` never writes file nodes, so ``verify`` is the only reader.)
        present = False
        if root is not None:
            cn_dir = root / "custom_nodes"
            for cand in (cn_dir / fn.filename, cn_dir / (fn.filename + ".disabled")):
                if is_within(root, cand) and cand.exists():
                    present = True
                    break
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
            # ``m.paths`` comes from the untrusted lockfile; confine the fallback
            # to the ComfyUI root so a malicious lock can't make verify stat/hash
            # an arbitrary absolute or ``../`` path (file-existence / content
            # oracle, or a hang on a device file). ``unpack`` confines the same way.
            cand = root / m.paths[0]
            path = cand if (is_within(root, cand) and cand.exists()) else None
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
