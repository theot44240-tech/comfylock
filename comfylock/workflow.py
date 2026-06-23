"""Extract model references and key parameters from a ComfyUI workflow.

Handles both workflow shapes:
  * API / "prompt" format: ``{node_id: {"class_type", "inputs": {...}}}``
  * UI graph / ``.flow.json``: ``{"nodes": [{"type", "widgets_values": [...]}]}``

Extraction is heuristic but format-agnostic: any string that looks like a model
file is collected, and a curated set of parameter names is echoed for diffing.
"""

from __future__ import annotations

from typing import Any

# File extensions that indicate a model/asset reference.
MODEL_EXTS = (
    ".safetensors",
    ".ckpt",
    ".pt",
    ".pth",
    ".bin",
    ".gguf",
    ".sft",
    ".onnx",
    ".vae",
    ".vae.pt",
    ".pdparams",
    ".msgpack",
)

# Parameter names worth echoing into the lock for semantic diffs.
PARAM_KEYS = (
    "seed",
    "noise_seed",
    "steps",
    "cfg",
    "sampler_name",
    "scheduler",
    "denoise",
    "width",
    "height",
    "batch_size",
)


def _looks_like_model(value: str) -> bool:
    v = value.strip().lower()
    if not v or "\n" in v:
        return False
    return v.endswith(MODEL_EXTS)


def extract_models(workflow: Any) -> list[str]:
    """Return a sorted, de-duplicated list of referenced model filenames."""
    found: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, str):
            if _looks_like_model(obj):
                found.add(obj.strip())
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v)

    walk(workflow)
    return sorted(found, key=str.lower)


def extract_params(workflow: Any) -> dict[str, Any]:
    """Collect a curated set of parameters keyed by name.

    For the API format we read node ``inputs``; for the UI format we read each
    node's ``inputs`` widget objects if present. Duplicate keys keep the first
    non-null value encountered (stable across runs because nodes are walked in
    document order).
    """
    params: dict[str, Any] = {}

    def consider(name: str, value: Any) -> None:
        if name in PARAM_KEYS and name not in params and isinstance(value, (int, float, str, bool)):
            params[name] = value

    # API / prompt format: top-level mapping of node objects with "inputs".
    if isinstance(workflow, dict) and "nodes" not in workflow:
        for node in workflow.values():
            if isinstance(node, dict) and isinstance(node.get("inputs"), dict):
                for k, v in node["inputs"].items():
                    consider(k, v)

    # UI graph format: list of nodes; inputs may be objects or widgets_values.
    nodes = workflow.get("nodes") if isinstance(workflow, dict) else None
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            # ``inputs`` is untrusted workflow data: a truthy non-iterable scalar
            # (e.g. ``"inputs": 5``) would make ``... or []`` keep the scalar and
            # ``for inp in 5`` raise an uncaught TypeError -> CLI traceback on
            # ``pack``. Only iterate when it is really a list/tuple.
            node_inputs = node.get("inputs")
            for inp in node_inputs if isinstance(node_inputs, (list, tuple)) else []:
                if isinstance(inp, dict) and "name" in inp:
                    consider(str(inp["name"]), inp.get("widget", {}).get("value")
                             if isinstance(inp.get("widget"), dict) else inp.get("value"))
    return params


def workflow_summary(workflow: Any) -> dict[str, Any]:
    return {
        "models": extract_models(workflow),
        "parameters": extract_params(workflow),
    }
