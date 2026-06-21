"""Read/write lockfiles. Canonical format is JSON; YAML supported as a bonus.

Format detection on read:
  * content starting with ``{`` -> JSON
  * otherwise -> YAML (requires PyYAML; a clear error is raised if missing)

On write, ``.json``/``.lock`` -> JSON, ``.yaml``/``.yml`` -> YAML (needs PyYAML).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import Lockfile

try:  # optional dependency
    import yaml  # type: ignore

    _HAS_YAML = True
except Exception:  # pragma: no cover - depends on environment
    _HAS_YAML = False


def dumps_json(lock: Lockfile) -> str:
    """Deterministic JSON text (stable key order, trailing newline)."""
    return json.dumps(lock.to_dict(), indent=2, ensure_ascii=False) + "\n"


def dumps_yaml(lock: Lockfile) -> str:
    if not _HAS_YAML:
        raise RuntimeError(
            "YAML output requires PyYAML (`pip install pyyaml`). "
            "Use a .json/.lock path for the zero-dependency JSON format."
        )
    return yaml.safe_dump(  # type: ignore[no-any-return]
        lock.to_dict(), sort_keys=False, default_flow_style=False, allow_unicode=True
    )


def loads(text: str) -> Lockfile:
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return Lockfile.from_dict(json.loads(text))
    if not _HAS_YAML:
        raise RuntimeError(
            "This lockfile looks like YAML but PyYAML is not installed. "
            "Install it (`pip install pyyaml`) or use a JSON lockfile."
        )
    return Lockfile.from_dict(yaml.safe_load(text) or {})  # type: ignore[arg-type]


def write(lock: Lockfile, path: str | Path) -> Path:
    p = Path(path)
    if p.suffix.lower() in (".yaml", ".yml"):
        text = dumps_yaml(lock)
    else:
        text = dumps_json(lock)
    p.write_text(text, encoding="utf-8")
    return p


def read(path: str | Path) -> Lockfile:
    p = Path(path)
    return loads(p.read_text(encoding="utf-8"))


def read_workflow(path: str | Path) -> Any:
    """Load a ComfyUI workflow JSON (UI graph or API/prompt format)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
