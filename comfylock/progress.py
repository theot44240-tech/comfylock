"""A tiny, dependency-free progress display for stderr.

Design rules (so it never gets in the way):
* Progress goes to **stderr** only -- ``comfy-lock pack ... | jq .`` keeps a clean
  machine-readable stdout.
* In a real terminal it draws a single carriage-return updated bar / byte count.
* When stderr is **not** a TTY, or ``NO_COLOR`` / ``CI`` is set, it degrades to
  occasional plain-text lines (or silence) so log files stay readable.
* Zero new dependencies: stdlib only.
"""

from __future__ import annotations

import os
import sys
from typing import TextIO

_SPINNER = "|/-\\"


def _env_truthy(name: str) -> bool:
    val = os.environ.get(name)
    return bool(val) and val != "0"


def progress_enabled(stream: TextIO | None = None) -> bool:
    """True if an animated bar should be drawn on ``stream`` (default stderr)."""
    stream = stream or sys.stderr
    if _env_truthy("NO_COLOR") or _env_truthy("CI"):
        return False
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(isatty and isatty())
    except (ValueError, OSError):  # pragma: no cover - closed stream
        return False


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000.0 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1000.0
    return f"{n:.1f}TB"  # pragma: no cover - unreachable


class ProgressBar:
    """A single-line download/hashing progress bar.

    ``update(done, total)`` redraws; ``finish()`` terminates the line. Safe to use
    when disabled (every method becomes a no-op), so callers need no branching.
    """

    def __init__(
        self,
        label: str = "",
        *,
        stream: TextIO | None = None,
        enabled: bool | None = None,
        width: int = 24,
    ) -> None:
        self.label = label
        self.stream = stream or sys.stderr
        self.enabled = progress_enabled(self.stream) if enabled is None else enabled
        self.width = width
        self._spin = 0
        self._last_line = ""
        self._done = False

    def render_line(self, done: int, total: int) -> str:
        """Build (but do not write) the status line -- exposed for testing."""
        prefix = f"{self.label} " if self.label else ""
        if total > 0:
            frac = max(0.0, min(1.0, done / total))
            filled = int(frac * self.width)
            bar = "#" * filled + "-" * (self.width - filled)
            return (
                f"{prefix}[{bar}] {frac * 100:5.1f}% "
                f"{_fmt_bytes(done)}/{_fmt_bytes(total)}"
            )
        self._spin = (self._spin + 1) % len(_SPINNER)
        return f"{prefix}{_SPINNER[self._spin]} {_fmt_bytes(done)}"

    def update(self, done: int, total: int) -> None:
        if not self.enabled or self._done:
            return
        line = self.render_line(done, total)
        pad = " " * max(0, len(self._last_line) - len(line))
        self.stream.write("\r" + line + pad)
        self.stream.flush()
        self._last_line = line

    def finish(self, message: str | None = None) -> None:
        if self._done:
            return
        self._done = True
        if not self.enabled:
            if message and not progress_enabled(self.stream):
                # one quiet completion line for non-TTY/CI logs
                self.stream.write(message.rstrip("\n") + "\n")
                self.stream.flush()
            return
        tail = f"  {message}" if message else ""
        self.stream.write("\r" + self._last_line + tail + "\n")
        self.stream.flush()

    # context-manager sugar
    def __enter__(self) -> ProgressBar:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.finish()


class Spinner:
    """A label + spinner for indeterminate work (e.g. hashing a large file)."""

    def __init__(
        self, label: str, *, stream: TextIO | None = None, enabled: bool | None = None
    ) -> None:
        self.bar = ProgressBar(label, stream=stream, enabled=enabled)

    def tick(self) -> None:
        self.bar.update(0, 0)

    def finish(self, message: str | None = None) -> None:
        self.bar.finish(message)
