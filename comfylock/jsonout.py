"""Shared ``--json`` envelope so machine-readable output is uniform everywhere.

Every ``--json`` result is the same shape::

    {"command", "version", "status": "ok|warning|error",
     "errors": [...], "warnings": [...], "data": {...}}

When ``--json`` is active the envelope is the only thing written to stdout (human
text goes to stderr), so the output always parses cleanly in a pipeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from . import __version__

OK = "ok"
WARNING = "warning"
ERROR = "error"


def status_for(errors: list[str], warnings: list[str]) -> str:
    if errors:
        return ERROR
    if warnings:
        return WARNING
    return OK


@dataclass
class Result:
    command: str
    status: str = OK
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def envelope(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "version": __version__,
            "status": self.status,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "data": self.data,
        }

    def dumps(self) -> str:
        return json.dumps(self.envelope(), indent=2)
