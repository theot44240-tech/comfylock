"""Shared result types and plain-text rendering for verify/diff output."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

OK = "OK"
WARN = "WARN"
ERROR = "ERROR"

_SYMBOL = {OK: "ok ", WARN: "!! ", ERROR: "XX "}


def _use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


_COLOR = {OK: "\033[32m", WARN: "\033[33m", ERROR: "\033[31m"}
_RESET = "\033[0m"


@dataclass
class Issue:
    severity: str
    message: str

    def render(self, color: bool) -> str:
        sym = _SYMBOL.get(self.severity, "   ")
        line = f"{sym}{self.message}"
        if color and self.severity in _COLOR:
            return f"{_COLOR[self.severity]}{line}{_RESET}"
        return line


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)

    def add(self, severity: str, message: str) -> None:
        self.issues.append(Issue(severity, message))

    def ok(self, message: str) -> None:
        self.add(OK, message)

    def warn(self, message: str) -> None:
        self.add(WARN, message)

    def error(self, message: str) -> None:
        self.add(ERROR, message)

    @property
    def n_errors(self) -> int:
        return sum(1 for i in self.issues if i.severity == ERROR)

    @property
    def n_warnings(self) -> int:
        return sum(1 for i in self.issues if i.severity == WARN)

    @property
    def passed(self) -> bool:
        return self.n_errors == 0

    def render(self, color: bool | None = None) -> str:
        if color is None:
            color = _use_color()
        lines = [i.render(color) for i in self.issues]
        summary = (
            f"\n{self.n_errors} error(s), {self.n_warnings} warning(s), "
            f"{len(self.issues)} check(s)."
        )
        return "\n".join(lines) + summary
