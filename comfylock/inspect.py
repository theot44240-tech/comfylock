"""`inspect` - a rich, human-readable summary of a lockfile.

Pure stdlib and dependency-free: aligned plain-text columns with optional ANSI
colour. ``--json`` re-emits the canonical lock JSON for piping into ``jq``.
"""

from __future__ import annotations

from . import serialize
from .model import Lockfile

_GREEN = "\033[32m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def human_size(n: int | None) -> str:
    """Format a byte count like ``6.47 GB`` (1000-based, matching disk vendors)."""
    if n is None:
        return "?"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1000 or unit == "PB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1000.0
    return f"{n} B"  # pragma: no cover - unreachable


def _hash_cells(model_hashes: list[tuple[str, str]]) -> str:
    return "  ".join(f"{t}:{v[:10]}{'…' if len(v) > 10 else ''}" for t, v in model_hashes)


def inspect_json(lock: Lockfile) -> str:
    """Re-emit the canonical lock JSON (stable key order, trailing newline)."""
    return serialize.dumps_json(lock)


def inspect_text(lock: Lockfile, color: bool = False) -> str:
    def c(code: str, text: str) -> str:
        return f"{code}{text}{_RESET}" if color else text

    out: list[str] = []
    title = f"ComfyLock  v{lock.version}"
    if lock.workflow:
        title += f"  ·  {lock.workflow}"
    if lock.generated:
        title += f"  ·  generated {lock.generated}"
    out.append(c(_BOLD, title))
    if lock.comfylock_version:
        out.append(c(_DIM, f"packed by comfylock {lock.comfylock_version}"))
    out.append("")

    out.append(c(_BOLD, "COMFYUI CORE"))
    out.append(f"  commit  {lock.comfyui or '(not pinned)'}")
    out.append("")

    nodes = sorted(lock.git_nodes.items())
    out.append(c(_BOLD, f"CUSTOM NODES  ({len(nodes) + len(lock.file_nodes)})"))
    name_w = max([10] + [len(_node_name(u)) for u, _ in nodes])
    for url, commit in nodes:
        out.append(f"  {c(_GREEN, '✓')}  {_node_name(url):<{name_w}}  {commit[:10]}  {url}")
    for fn in sorted(lock.file_nodes, key=lambda f: f.filename):
        flag = " (disabled)" if fn.disabled else ""
        out.append(f"  {c(_GREEN, '✓')}  {fn.filename}{flag}")
    if not nodes and not lock.file_nodes:
        out.append("  (none)")
    out.append("")

    total = 0
    out.append(c(_BOLD, f"MODELS  ({len(lock.models)})"))
    if lock.models:
        nw = max(len(m.name) for m in lock.models)
        tw = max([4] + [len(m.type or "") for m in lock.models])
        out.append(f"  {'name':<{nw}}  {'type':<{tw}}  {'size':>9}  hashes")
        for m in sorted(lock.models, key=lambda m: m.name.lower()):
            if m.size:
                total += m.size
            cells = _hash_cells([(h.type, h.hash) for h in m.hashes])
            out.append(
                f"  {m.name:<{nw}}  {(m.type or ''):<{tw}}  "
                f"{human_size(m.size):>9}  {cells}"
            )
    else:
        out.append("  (none)")
    out.append("")

    if lock.parameters:
        out.append(c(_BOLD, "PARAMETERS"))
        cells = "  ·  ".join(f"{k}  {v}" for k, v in sorted(lock.parameters.items()))
        out.append(f"  {cells}")
        out.append("")

    out.append(c(_BOLD, "LOCKFILE"))
    out.append(
        f"  schema version  {lock.version}  ·  "
        f"models  {len(lock.models)}  ·  models total  ~{human_size(total)}"
    )
    return "\n".join(out)


def _node_name(url: str) -> str:
    seg = url.rstrip("/").replace("\\", "/").rstrip("/").split("/")[-1]
    return seg[:-4] if seg.endswith(".git") else seg
