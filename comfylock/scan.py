"""Scan a ComfyUI installation: core commit, custom nodes, model files."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .model import FileNode

# Subdirectories of models/ are searched for model files, but we glob the whole
# models tree anyway so any layout works.
DEFAULT_COMFY_ROOTS = (
    "ComfyUI",
    ".",
)


def git(args: list[str], cwd: str | Path) -> str | None:
    """Run a git command, returning stripped stdout or None on any failure."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def is_git_repo(path: str | Path) -> bool:
    return git(["rev-parse", "--is-inside-work-tree"], path) == "true"


def head_commit(path: str | Path) -> str | None:
    return git(["rev-parse", "HEAD"], path)


def remote_url(path: str | Path) -> str | None:
    url = git(["config", "--get", "remote.origin.url"], path)
    if not url:
        return None
    # Normalize scp-style git@host:owner/repo.git to https for portability.
    if url.startswith("git@"):
        host, _, rest = url[4:].partition(":")
        url = f"https://{host}/{rest}"
    return url


def scan_comfyui_commit(root: str | Path) -> str | None:
    root = Path(root)
    return head_commit(root) if is_git_repo(root) else None


def scan_custom_nodes(root: str | Path) -> tuple[dict[str, str], list[FileNode]]:
    """Return ({repo_url: commit}, [FileNode,...]) for custom_nodes/."""
    root = Path(root)
    cn = root / "custom_nodes"
    git_nodes: dict[str, str] = {}
    file_nodes: list[FileNode] = []
    if not cn.is_dir():
        return git_nodes, file_nodes
    for entry in sorted(cn.iterdir(), key=lambda p: p.name.lower()):
        if entry.name == "__pycache__":
            continue
        if entry.is_dir() and is_git_repo(entry):
            url = remote_url(entry)
            commit = head_commit(entry)
            if url and commit:
                git_nodes[url] = commit
        elif entry.is_file() and entry.suffix in (".py", ".disabled"):
            disabled = entry.suffix == ".disabled" or entry.name.startswith("_")
            name = entry.name[:-9] if entry.name.endswith(".disabled") else entry.name
            file_nodes.append(FileNode(filename=name, disabled=disabled))
    return git_nodes, file_nodes


def locate_models(root: str | Path, filenames: list[str]) -> dict[str, Path]:
    """Map each requested filename to an on-disk path under models/ (if found).

    Matching is by basename, so a workflow that references ``model.safetensors``
    resolves regardless of which subfolder it lives in.
    """
    root = Path(root)
    models_dir = root / "models"
    index: dict[str, Path] = {}
    if models_dir.is_dir():
        for p in models_dir.rglob("*"):
            if p.is_file():
                index.setdefault(p.name, p)
    result: dict[str, Path] = {}
    for fn in filenames:
        base = Path(fn).name
        if base in index:
            result[fn] = index[base]
    return result


def relpath(root: str | Path, path: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
