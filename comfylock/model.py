"""Lockfile data model and (de)serialization.

The canonical on-disk format is JSON (deterministic, zero-dependency). YAML is
supported on read, and on write when PyYAML is installed (see ``io`` module).
The in-memory model below is format-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1


def _as_int(value: Any, default: int | None) -> int | None:
    """Coerce an untrusted lockfile field to int, falling back on garbage.

    Hand-authored locks may carry non-numeric ``version``/``size`` values
    (e.g. ``"abc"`` or a list). A bare ``int()`` would raise ValueError/TypeError
    that escapes the CLI error handler as a traceback, so degrade gracefully.
    ``json``/``yaml`` also parse ``1e400`` / ``.inf`` to a float ``inf``, and
    ``int(inf)`` raises OverflowError (``int(nan)`` raises ValueError); catch that
    too so a hostile numeric field cannot crash verify/diff with a traceback.
    """
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


# Hash type identifiers, compatible with comfy-cli's comfy-lock.yaml.
HASH_TYPES = ("SHA256", "BLAKE3", "BLAKE2B", "CRC32", "AutoV1", "AutoV2")


@dataclass
class Hash:
    type: str
    hash: str

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "hash": self.hash}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Hash:
        # Every supported hash type is hex and ``compute()`` emits lowercase, so
        # canonicalize the stored digest to lowercase on ingest. A lock authored
        # elsewhere (Civitai AutoV2 / A1111 AutoV1 digests are commonly UPPERCASE)
        # then compares equal to a freshly computed hash instead of spuriously
        # failing verify/unpack or showing a phantom change in diff.
        return Hash(
            type=str(d.get("type", "")),
            hash=str(d.get("hash", "")).lower(),
        )


@dataclass
class Model:
    name: str
    url: str | None = None
    paths: list[str] = field(default_factory=list)
    hashes: list[Hash] = field(default_factory=list)
    type: str | None = None
    size: int | None = None
    present: bool = True

    def hash_of(self, hash_type: str) -> str | None:
        for h in self.hashes:
            if h.type.lower() == hash_type.lower():
                return h.hash
        return None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name}
        if self.url:
            d["url"] = self.url
        if self.paths:
            d["paths"] = [{"path": p} for p in self.paths]
        if self.hashes:
            d["hashes"] = [h.to_dict() for h in self.hashes]
        if self.type:
            d["type"] = self.type
        if self.size is not None:
            d["size"] = self.size
        if not self.present:
            d["present"] = False
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Model:
        raw_paths = d.get("paths", []) or []
        if not isinstance(raw_paths, list):
            raw_paths = []
        paths: list[str] = []
        for p in raw_paths:
            if isinstance(p, dict):
                paths.append(str(p.get("path", "")))
            else:
                paths.append(str(p))
        raw_hashes = d.get("hashes", []) or []
        hashes = [
            Hash.from_dict(h)
            for h in (raw_hashes if isinstance(raw_hashes, list) else [])
            if isinstance(h, dict)
        ]
        size = d.get("size")
        return Model(
            name=str(d.get("name", "")),
            url=d.get("url"),
            paths=[p for p in paths if p],
            hashes=hashes,
            type=d.get("type"),
            size=_as_int(size, None),
            present=bool(d.get("present", True)),
        )


@dataclass
class FileNode:
    filename: str
    disabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"filename": self.filename, "disabled": self.disabled}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> FileNode:
        return FileNode(
            filename=str(d.get("filename", "")),
            disabled=bool(d.get("disabled", False)),
        )


@dataclass
class Lockfile:
    workflow: str | None = None
    comfyui: str | None = None
    generated: str | None = None
    git_nodes: dict[str, str] = field(default_factory=dict)  # repo url -> commit
    file_nodes: list[FileNode] = field(default_factory=list)
    models: list[Model] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict with deterministic ordering."""
        d: dict[str, Any] = {"version": self.version}
        if self.workflow:
            d["workflow"] = self.workflow
        if self.generated:
            d["generated"] = self.generated
        if self.comfyui:
            d["comfyui"] = self.comfyui
        custom: dict[str, Any] = {}
        if self.git_nodes:
            custom["git"] = {k: self.git_nodes[k] for k in sorted(self.git_nodes)}
        if self.file_nodes:
            custom["files"] = [
                fn.to_dict() for fn in sorted(self.file_nodes, key=lambda f: f.filename)
            ]
        if custom:
            d["custom_nodes"] = custom
        if self.models:
            d["models"] = [
                m.to_dict() for m in sorted(self.models, key=lambda m: m.name.lower())
            ]
        if self.parameters:
            d["parameters"] = {k: self.parameters[k] for k in sorted(self.parameters)}
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Lockfile:
        custom = d.get("custom_nodes", {}) or {}
        if not isinstance(custom, dict):
            custom = {}
        raw_git = custom.get("git", {}) or {}
        git_nodes = (
            {str(k): str(v) for k, v in raw_git.items()}
            if isinstance(raw_git, dict)
            else {}
        )
        raw_files = custom.get("files", []) or []
        file_nodes = [
            FileNode.from_dict(f)
            for f in (raw_files if isinstance(raw_files, list) else [])
            if isinstance(f, dict)
        ]
        raw_models = d.get("models", []) or []
        models = [
            Model.from_dict(m)
            for m in (raw_models if isinstance(raw_models, list) else [])
            if isinstance(m, dict)
        ]
        raw_params = d.get("parameters", {}) or {}
        parameters = dict(raw_params) if isinstance(raw_params, dict) else {}
        version = _as_int(d.get("version", SCHEMA_VERSION), SCHEMA_VERSION)
        return Lockfile(
            version=version if version is not None else SCHEMA_VERSION,
            workflow=d.get("workflow"),
            comfyui=d.get("comfyui"),
            generated=d.get("generated"),
            git_nodes=git_nodes,
            file_nodes=file_nodes,
            models=models,
            parameters=parameters,
        )
