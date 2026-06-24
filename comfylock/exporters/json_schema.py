"""JSON Schema (draft-07) for ComfyLock ``.lock`` files (v1 and v2).

This is the single source of truth: ``comfy-lock export --format json-schema``
emits it, and ``schema/comfylock-v2.schema.json`` in the repo is generated from
it. Kept permissive enough that every lock this tool writes validates, while
still catching gross structural mistakes.
"""

from __future__ import annotations

import json
from typing import Any

_HASH = {
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "hash": {"type": "string"},
    },
    "required": ["type", "hash"],
    "additionalProperties": True,
}

_MODEL = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "url": {"type": "string"},
        "mirrors": {"type": "array", "items": {"type": "string"}},
        "paths": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        "hashes": {"type": "array", "items": _HASH},
        "type": {"type": "string"},
        "size": {"type": "integer", "minimum": 0},
        "present": {"type": "boolean"},
        "civitai_model_id": {"type": "integer"},
        "civitai_version_id": {"type": "integer"},
        "hf_repo_id": {"type": "string"},
        "hf_filename": {"type": "string"},
    },
    "required": ["name"],
    "additionalProperties": True,
}

LOCK_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "https://github.com/theot44240-tech/comfylock/schema/comfylock-v2.schema.json",
    "title": "ComfyLock lockfile",
    "description": "A ComfyLock .lock file pinning a ComfyUI environment (schema v1 and v2).",
    "type": "object",
    "properties": {
        "version": {"type": "integer", "minimum": 1},
        "workflow": {"type": "string"},
        "generated": {"type": "string"},
        "comfylock_version": {"type": "string"},
        "provenance": {"type": "object"},
        "comfyui": {"type": "string"},
        "custom_nodes": {
            "type": "object",
            "properties": {
                "git": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string"},
                            "disabled": {"type": "boolean"},
                        },
                        "required": ["filename"],
                    },
                },
            },
            "additionalProperties": True,
        },
        "models": {"type": "array", "items": _MODEL},
        "parameters": {"type": "object"},
        "thumbnail": {"type": ["string", "null"]},
    },
    "required": ["version"],
    "additionalProperties": True,
}


def to_json_schema() -> str:
    return json.dumps(LOCK_SCHEMA, indent=2, ensure_ascii=False) + "\n"
