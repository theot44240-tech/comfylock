"""`init` - a friendly interactive wizard for first-time users.

Stdlib ``input()`` only -- no TUI dependency. In a non-interactive context
(no TTY) it explains how to use the flags instead of hanging on a prompt.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .pack import pack


def candidate_roots() -> list[Path]:
    """Common ComfyUI install locations, existing ones first."""
    env = os.environ.get("COMFYUI_ROOT")
    raw = [
        Path(env) if env else None,
        Path.cwd() / "ComfyUI",
        Path.home() / "ComfyUI",
        Path.home() / "Documents" / "ComfyUI",
    ]
    seen: dict[str, Path] = {}
    for p in raw:
        if p is not None:
            seen.setdefault(str(p), p)
    cands = list(seen.values())
    return sorted(cands, key=lambda p: (not p.exists(), str(p)))


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        return default
    return ans or default


def run_init(out=sys.stdout) -> int:
    if not sys.stdin.isatty():
        print(
            "comfy-lock init is interactive. In a script, run "
            "`comfy-lock pack <workflow> -r <ComfyUI root>` directly instead.",
            file=sys.stderr,
        )
        return 2

    print("🔒 ComfyLock setup wizard", file=out)
    roots = candidate_roots()
    default_root = next((str(r) for r in roots if r.exists()), str(roots[0]) if roots else "")
    root = _ask("Where is your ComfyUI installation?", default_root)
    workflow = _ask("Which workflow file to pin?")
    if not workflow:
        print("No workflow given; nothing to do.", file=sys.stderr)
        return 2
    algo = _ask("Hash algorithm? (SHA256 / AutoV2 / BLAKE3)", "SHA256")
    include = _ask("Include model hashes? (can be slow for large models) (Y/n)", "Y")
    hash_types = [algo] if include.lower().startswith("y") else []
    out_default = str(Path(workflow).with_suffix("").with_suffix(".lock"))
    out_path = _ask("Save lockfile as", out_default)

    try:
        written = pack(
            workflow,
            out_path=out_path,
            comfyui_root=root or None,
            hash_types=hash_types or None,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    from .inspect import inspect_text
    from .serialize import read

    print(f"\nWrote {written}\n", file=out)
    print(inspect_text(read(written)), file=out)
    return 0
