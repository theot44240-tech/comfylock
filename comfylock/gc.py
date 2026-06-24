"""`gc` - find (and optionally delete) model files not referenced by any lock.

Walks every ``*.lock`` under ``locks_dir``, collects the model files they
reference (by basename, so it is robust to differing absolute paths), then walks
``<root>/models`` and reports any model file whose basename no lock mentions.

Deletion is never implicit: it requires ``delete=True`` *and* (at the CLI layer)
an interactive confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import serialize
from .workflow import MODEL_EXTS


@dataclass
class Orphan:
    path: Path
    size: int


@dataclass
class GcResult:
    orphans: list[Orphan] = field(default_factory=list)
    scanned_locks: int = 0

    @property
    def total_bytes(self) -> int:
        return sum(o.size for o in self.orphans)

    def render(self) -> str:
        from .inspect import human_size

        if not self.orphans:
            return f"No orphaned models (scanned {self.scanned_locks} lock(s))."
        lines = [f"Orphaned model files (not referenced by any of "
                 f"{self.scanned_locks} lock(s)):", ""]
        nw = max(len(str(o.path)) for o in self.orphans)
        for o in sorted(self.orphans, key=lambda o: str(o.path)):
            lines.append(f"  {str(o.path):<{nw}}  {human_size(o.size)}")
        lines.append("")
        lines.append(f"Total reclaimable: {human_size(self.total_bytes)}")
        return "\n".join(lines)


def referenced_basenames(locks_dir: str | Path) -> tuple[set[str], int]:
    """Return ({referenced model basenames}, n_locks) across all *.lock files."""
    locks_dir = Path(locks_dir)
    names: set[str] = set()
    count = 0
    for lock_path in sorted(locks_dir.rglob("*.lock")):
        if not lock_path.is_file():
            continue
        try:
            lock = serialize.read(lock_path)
        except (RuntimeError, OSError):
            continue
        count += 1
        for m in lock.models:
            if m.name:
                names.add(Path(m.name).name)
            for p in m.paths:
                names.add(Path(p).name)
    return names, count


def find_orphans(comfyui_root: str | Path, locks_dir: str | Path = ".") -> GcResult:
    root = Path(comfyui_root)
    referenced, n_locks = referenced_basenames(locks_dir)
    result = GcResult(scanned_locks=n_locks)
    models_dir = root / "models"
    if not models_dir.is_dir():
        return result
    for f in sorted(models_dir.rglob("*")):
        if not f.is_file():
            continue
        if f.suffix.lower() not in MODEL_EXTS:
            continue
        if f.name in referenced:
            continue
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        result.orphans.append(Orphan(path=f, size=size))
    return result


def delete_orphans(result: GcResult) -> list[Path]:
    """Delete the orphan files; return the paths actually removed."""
    removed: list[Path] = []
    for o in result.orphans:
        try:
            o.path.unlink()
            removed.append(o.path)
        except OSError:
            pass
    return removed
