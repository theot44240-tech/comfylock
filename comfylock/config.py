"""``comfylock.toml`` project configuration.

A small, optional config file lets a project record its defaults once instead of
repeating ``-r``/``--hash``/``--jobs`` on every command. Like ``git`` reading
``.gitconfig`` from the working tree upward, ``find_config`` searches the current
directory and its ancestors for ``comfylock.toml`` and reads its ``[comfylock]``
table.

Zero dependencies on every supported Python: ``tomllib`` is used when present
(3.11+); otherwise a deliberately tiny TOML reader parses the small subset this
config needs (the ``[comfylock]`` table with string / int / bool / string-array
values). CLI flags always win over the file -- see :func:`merge`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib as _tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.9/3.10 CI
    _tomllib = None  # type: ignore[assignment]

CONFIG_NAME = "comfylock.toml"

# The keys we recognise under [comfylock]. Unknown keys are ignored (forward
# compatible) rather than rejected.
_KNOWN_KEYS = (
    "comfyui_root",
    "hash",
    "default_hash",
    "jobs",
    "enrich",
    "schema_version",
    "workflow_dir",
    "output_dir",
    "annotate",
)


def find_config(start: str | Path | None = None) -> Path | None:
    """Return the nearest ``comfylock.toml`` at or above ``start`` (or None)."""
    here = Path(start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def _coerce_scalar(raw: str) -> Any:
    """Parse a single TOML scalar from the minimal fallback reader."""
    raw = raw.strip()
    if not raw:
        return ""
    if raw[0] in "\"'":
        # quoted string: take up to the matching closing quote, ignore any trailing
        # inline comment (``"hi"  # note``).
        quote = raw[0]
        end = raw.find(quote, 1)
        if end != -1:
            return raw[1:end]
        return raw[1:]
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw


def _parse_array(raw: str) -> list[Any]:
    """Parse a single-line ``["a", "b"]`` TOML array (no nesting)."""
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return []
    return [_coerce_scalar(piece) for piece in inner.split(",") if piece.strip()]


def _parse_minimal(text: str) -> dict[str, dict[str, Any]]:
    """Tiny TOML subset reader for Python < 3.11 (no ``tomllib``).

    Understands ``# comments``, ``[table]`` / ``[tool.table]`` headers, and
    ``key = value`` lines whose value is a quoted string, int, float, bool or a
    single-line array of those. Anything else on a line is ignored, never raised:
    a config file should never crash a command.
    """
    tables: dict[str, dict[str, Any]] = {}
    current = ""
    tables[current] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip()
            tables.setdefault(current, {})
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        # strip a trailing inline comment from unquoted values
        value = value.strip()
        if value[:1] not in "\"'[" and "#" in value:
            value = value.split("#", 1)[0].strip()
        if value.startswith("["):
            tables[current][key] = _parse_array(value)
        else:
            tables[current][key] = _coerce_scalar(value)
    return tables


def _load_toml(text: str) -> dict[str, Any]:
    if _tomllib is not None:
        try:
            return _tomllib.loads(text)
        except Exception:  # pragma: no cover - malformed config degrades to {}
            return {}
    tables = _parse_minimal(text)
    # Re-shape ``tool.comfylock`` into a nested ``tool`` table so the section
    # lookup below works the same way under both readers.
    out: dict[str, Any] = {}
    for name, body in tables.items():
        if not name:
            out.update(body)
        elif "." in name:
            head, _, tail = name.partition(".")
            out.setdefault(head, {})[tail] = body
        else:
            out[name] = body
    return out


def _section(data: dict[str, Any]) -> dict[str, Any]:
    """Pick the ``[comfylock]`` table, or the ``[tool.comfylock]`` table."""
    if isinstance(data.get("comfylock"), dict):
        return data["comfylock"]
    tool = data.get("tool")
    if isinstance(tool, dict) and isinstance(tool.get("comfylock"), dict):
        return tool["comfylock"]
    return {}


def load_config(start: str | Path | None = None) -> dict[str, Any]:
    """Discover and read the ``[comfylock]`` table; ``{}`` if none/unreadable."""
    path = find_config(start)
    if path is None:
        return read_config_file(None)
    return read_config_file(path)


def read_config_file(path: str | Path | None) -> dict[str, Any]:
    """Read one config file's ``[comfylock]`` table (no discovery)."""
    if path is None:
        return {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    section = _section(_load_toml(text))
    return {k: v for k, v in section.items() if k in _KNOWN_KEYS}


def merge(cli_value: Any, config: dict[str, Any], key: str) -> Any:
    """Return ``cli_value`` if the user passed it, else the config value.

    ``cli_value`` of ``None`` (or an empty list) means "flag not given", so the
    config provides the default. A CLI flag always wins when present.
    """
    if cli_value not in (None, [], ()):
        return cli_value
    if key in config:
        return config[key]
    # accept default_hash as an alias for hash
    if key == "hash" and "default_hash" in config:
        return config["default_hash"]
    return cli_value
