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


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        inner = ", ".join(_toml_value(v) for v in value)
        return f"[{inner}]"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_config(
    path: str | Path,
    *,
    comfyui_root: str,
    default_hash: list[str] | None = None,
    workflow_dir: str = "workflows/",
    output_dir: str = "locks/",
    schema_version: int = 2,
) -> Path:
    """Write a ``comfylock.toml`` project config. Returns the path."""
    default_hash = default_hash or ["SHA256", "AutoV2"]
    lines = [
        "# ComfyLock project config -- https://github.com/theot44240-tech/comfylock",
        "[comfylock]",
        f"comfyui_root = {_toml_value(comfyui_root)}",
        f"default_hash = {_toml_value(default_hash)}",
        f"workflow_dir = {_toml_value(workflow_dir)}",
        f"output_dir = {_toml_value(output_dir)}",
        f"schema_version = {_toml_value(schema_version)}",
        "",
    ]
    p = Path(path)
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _gitignore_cache(cwd: Path) -> None:
    """Add the hash cache to .gitignore if one exists and lacks the entry."""
    gi = cwd / ".gitignore"
    if not gi.is_file():
        return
    try:
        text = gi.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return
    if ".comfylock-cache.json" not in text:
        with gi.open("a", encoding="utf-8") as fh:
            fh.write("\n# ComfyLock\n.comfylock-cache.json\n")


def run_init(
    out=sys.stdout,
    *,
    comfyui_root: str | None = None,
    non_interactive: bool = False,
) -> int:
    cwd = Path.cwd()
    config_path = cwd / "comfylock.toml"
    roots = candidate_roots()
    default_root = comfyui_root or next(
        (str(r) for r in roots if r.exists()), str(roots[0]) if roots else ""
    )

    if non_interactive or not sys.stdin.isatty():
        if not default_root:
            print(
                "error: no ComfyUI root found. Pass --comfyui-root <path>.",
                file=sys.stderr,
            )
            return 2
        write_config(config_path, comfyui_root=default_root)
        _gitignore_cache(cwd)
        print(f"Wrote {config_path}", file=out)
        print(
            "Quick start:\n"
            "  comfy-lock pack <workflow.json>      # uses comfyui_root from config\n"
            "  comfy-lock verify <workflow.lock>\n"
            "  comfy-lock sync <workflow.lock> --check-only   # CI: alert on stale pins",
            file=out,
        )
        return 0

    print("🔒 ComfyLock setup wizard", file=out)
    root = _ask("Where is your ComfyUI installation?", default_root)
    algo = _ask("Default hash algorithm? (SHA256 / AutoV2 / BLAKE3)", "SHA256")
    write_config(config_path, comfyui_root=root, default_hash=[algo])
    _gitignore_cache(cwd)
    print(f"\nWrote {config_path}", file=out)

    workflow = _ask("Pack a workflow now? (path, or blank to skip)")
    if not workflow:
        print("Setup complete. Run `comfy-lock pack <workflow>` when ready.", file=out)
        return 0
    include = _ask("Include model hashes? (can be slow for large models) (Y/n)", "Y")
    hash_types = [algo] if include.lower().startswith("y") else []
    out_path = str(Path(workflow).with_suffix("").with_suffix(".lock"))
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
