"""Lockfile data model and (de)serialization.

The canonical on-disk format is JSON (deterministic, zero-dependency). YAML is
supported on read, and on write when PyYAML is installed (see ``io`` module).
The in-memory model below is format-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Schema v2 (current) adds optional, backward-compatible fields: download
# mirrors and Civitai/HuggingFace metadata on models, plus tool-version and
# provenance/thumbnail metadata on the lock. A v1 lock omits all of them and
# still reads/writes correctly; ``pack --lock-version 1`` emits v1 on request.
SCHEMA_VERSION = 2


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
    # --- schema v2 (optional) ---
    mirrors: list[str] = field(default_factory=list)
    civitai_model_id: int | None = None
    civitai_version_id: int | None = None
    hf_repo_id: str | None = None
    hf_filename: str | None = None

    def hash_of(self, hash_type: str) -> str | None:
        for h in self.hashes:
            if h.type.lower() == hash_type.lower():
                return h.hash
        return None

    def urls(self) -> list[str]:
        """Ordered, de-duplicated download URLs: the primary first, then mirrors."""
        seen: dict[str, None] = {}
        for u in ([self.url] if self.url else []) + self.mirrors:
            if u and u not in seen:
                seen[u] = None
        return list(seen)

    def to_dict(self, v2: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name}
        if self.url:
            d["url"] = self.url
        if v2 and self.mirrors:
            d["mirrors"] = list(self.mirrors)
        if self.paths:
            d["paths"] = [{"path": p} for p in self.paths]
        if self.hashes:
            d["hashes"] = [h.to_dict() for h in self.hashes]
        if self.type:
            d["type"] = self.type
        if self.size is not None:
            d["size"] = self.size
        if v2:
            if self.civitai_model_id is not None:
                d["civitai_model_id"] = self.civitai_model_id
            if self.civitai_version_id is not None:
                d["civitai_version_id"] = self.civitai_version_id
            if self.hf_repo_id:
                d["hf_repo_id"] = self.hf_repo_id
            if self.hf_filename:
                d["hf_filename"] = self.hf_filename
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
        raw_mirrors = d.get("mirrors", []) or []
        mirrors = [
            str(u)
            for u in (raw_mirrors if isinstance(raw_mirrors, list) else [])
            if isinstance(u, str) and u
        ]
        hf_repo = d.get("hf_repo_id")
        hf_file = d.get("hf_filename")
        return Model(
            name=str(d.get("name", "")),
            url=d.get("url"),
            paths=[p for p in paths if p],
            hashes=hashes,
            type=d.get("type"),
            size=_as_int(d.get("size"), None),
            present=bool(d.get("present", True)),
            mirrors=mirrors,
            civitai_model_id=_as_int(d.get("civitai_model_id"), None),
            civitai_version_id=_as_int(d.get("civitai_version_id"), None),
            hf_repo_id=str(hf_repo) if isinstance(hf_repo, str) and hf_repo else None,
            hf_filename=str(hf_file) if isinstance(hf_file, str) and hf_file else None,
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
    # --- schema v2 (optional) ---
    comfylock_version: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    thumbnail: str | None = None
    workflow_hash: str | None = None
    environment: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)
    pip_requirements: list[str] = field(default_factory=list)

    def copy(self) -> Lockfile:
        """A deep-enough copy (containers duplicated; dataclass leaves shared)."""
        return Lockfile(
            workflow=self.workflow,
            comfyui=self.comfyui,
            generated=self.generated,
            git_nodes=dict(self.git_nodes),
            file_nodes=list(self.file_nodes),
            models=list(self.models),
            parameters=dict(self.parameters),
            version=self.version,
            comfylock_version=self.comfylock_version,
            provenance=dict(self.provenance),
            thumbnail=self.thumbnail,
            workflow_hash=self.workflow_hash,
            environment=dict(self.environment),
            annotations=dict(self.annotations),
            pip_requirements=list(self.pip_requirements),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict with deterministic ordering.

        v2-only fields (``comfylock_version``, ``provenance``, ``thumbnail`` and
        the v2 model metadata) are emitted only when ``version >= 2``, so a lock
        written with ``--lock-version 1`` is byte-compatible with a v1 reader.
        """
        v2 = self.version >= 2
        d: dict[str, Any] = {"version": self.version}
        if self.workflow:
            d["workflow"] = self.workflow
        if v2 and self.workflow_hash:
            d["workflow_hash"] = self.workflow_hash
        if self.generated:
            d["generated"] = self.generated
        if v2 and self.comfylock_version:
            d["comfylock_version"] = self.comfylock_version
        if v2 and self.environment:
            d["environment"] = {k: self.environment[k] for k in sorted(self.environment)}
        if v2 and self.annotations:
            d["annotations"] = {k: self.annotations[k] for k in sorted(self.annotations)}
        if v2 and self.provenance:
            d["provenance"] = self.provenance
        if self.comfyui:
            d["comfyui"] = self.comfyui
        custom: dict[str, Any] = {}
        if self.git_nodes:
            custom["git"] = {k: self.git_nodes[k] for k in sorted(self.git_nodes)}
        if self.file_nodes:
            custom["files"] = [
                fn.to_dict() for fn in sorted(self.file_nodes, key=lambda f: f.filename)
            ]
        if v2 and self.pip_requirements:
            custom["pip"] = sorted(self.pip_requirements)
        if custom:
            d["custom_nodes"] = custom
        if self.models:
            d["models"] = [
                m.to_dict(v2=v2) for m in sorted(self.models, key=lambda m: m.name.lower())
            ]
        if self.parameters:
            d["parameters"] = {k: self.parameters[k] for k in sorted(self.parameters)}
        if v2 and self.thumbnail:
            d["thumbnail"] = self.thumbnail
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
        raw_pip = custom.get("pip", []) or []
        pip_requirements = [
            str(r)
            for r in (raw_pip if isinstance(raw_pip, list) else [])
            if isinstance(r, str) and r
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
        raw_prov = d.get("provenance", {}) or {}
        provenance = dict(raw_prov) if isinstance(raw_prov, dict) else {}
        clv = d.get("comfylock_version")
        thumb = d.get("thumbnail")
        wf_hash = d.get("workflow_hash")
        raw_env = d.get("environment", {}) or {}
        environment = dict(raw_env) if isinstance(raw_env, dict) else {}
        raw_ann = d.get("annotations", {}) or {}
        annotations = dict(raw_ann) if isinstance(raw_ann, dict) else {}
        return Lockfile(
            version=version if version is not None else SCHEMA_VERSION,
            workflow=d.get("workflow"),
            comfyui=d.get("comfyui"),
            generated=d.get("generated"),
            git_nodes=git_nodes,
            file_nodes=file_nodes,
            models=models,
            parameters=parameters,
            comfylock_version=str(clv) if isinstance(clv, str) and clv else None,
            provenance=provenance,
            thumbnail=str(thumb) if isinstance(thumb, str) and thumb else None,
            workflow_hash=str(wf_hash) if isinstance(wf_hash, str) and wf_hash else None,
            environment=environment,
            annotations=annotations,
            pip_requirements=pip_requirements,
        )
