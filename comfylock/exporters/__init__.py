"""Export a lockfile to other formats: Markdown, ComfyUI-Manager snapshot,
Dockerfile, or a JSON Schema for ``.lock`` validation.

Each exporter is a small, dependency-free function returning text. ``export``
dispatches by format name.
"""

from __future__ import annotations

from ..model import Lockfile
from .dockerfile import to_dockerfile
from .json_schema import to_json_schema
from .manager_snapshot import to_manager_snapshot
from .markdown import to_markdown
from .requirements import to_requirements
from .shell import to_shell

FORMATS = (
    "markdown",
    "manager-snapshot",
    "dockerfile",
    "json-schema",
    "shell",
    "requirements",
)


def export(lock: Lockfile, fmt: str) -> str:
    if fmt == "markdown":
        return to_markdown(lock)
    if fmt == "manager-snapshot":
        return to_manager_snapshot(lock)
    if fmt == "dockerfile":
        return to_dockerfile(lock)
    if fmt == "json-schema":
        return to_json_schema()
    if fmt == "shell":
        return to_shell(lock)
    if fmt == "requirements":
        return to_requirements(lock)
    raise RuntimeError(f"Unknown export format {fmt!r}. Valid: {', '.join(FORMATS)}.")


__all__ = [
    "FORMATS",
    "export",
    "to_markdown",
    "to_manager_snapshot",
    "to_dockerfile",
    "to_json_schema",
    "to_shell",
    "to_requirements",
]
