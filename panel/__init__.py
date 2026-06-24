"""ComfyLock ComfyUI extension.

Drop this ``panel`` folder into ``ComfyUI/custom_nodes/`` (or symlink it) and
install the ``comfylock`` package (``pip install comfylock``). It adds ComfyLock
buttons and a status badge to the ComfyUI menu that pin / verify / inspect the
current graph's models, custom-node commits, and key parameters.

The extension registers HTTP routes under ``/comfylock/`` on ComfyUI's aiohttp
server. All imports are guarded so importing this module outside of a running
ComfyUI (e.g. during tests or linting) never raises.
"""

from __future__ import annotations

import os
from typing import Any

# ComfyUI looks for these two module-level names in every custom node.
NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]


def _comfyui_root() -> str:
    # ComfyUI runs from its repo root; fall back to CWD.
    return os.environ.get("COMFYUI_ROOT") or os.getcwd()


def _lock_from_body(body: dict) -> Any:
    """Build a Lockfile from a request body: a posted lock dict, or a packed graph."""
    from comfylock.model import Lockfile

    if isinstance(body.get("lock"), dict):
        return Lockfile.from_dict(body["lock"])
    from comfylock.pack import build_lock

    workflow = body.get("workflow", body)
    return build_lock(
        workflow,
        workflow_name=body.get("name", "workflow.flow.json"),
        comfyui_root=_comfyui_root(),
        hash_types=body.get("hash_types") or ["SHA256"],
    )


try:  # Only succeeds inside a running ComfyUI process.
    from aiohttp import web  # type: ignore
    from server import PromptServer  # type: ignore

    _routes = PromptServer.instance.routes

    @_routes.post("/comfylock/pack")
    async def _comfylock_pack(request):  # pragma: no cover - needs ComfyUI runtime
        try:
            from comfylock.pack import build_lock
            from comfylock.serialize import dumps_json
        except Exception as exc:
            return web.json_response(
                {"error": f"comfylock package not installed: {exc}"}, status=500
            )
        try:
            body = await request.json()
            workflow = body.get("workflow", body)
            hash_types = body.get("hash_types") or ["SHA256"]
            lock = build_lock(
                workflow,
                workflow_name=body.get("name", "workflow.flow.json"),
                comfyui_root=_comfyui_root(),
                hash_types=hash_types,
            )
            return web.Response(
                text=dumps_json(lock),
                content_type="application/json",
                headers={"Content-Disposition": 'attachment; filename="workflow.lock"'},
            )
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)

    @_routes.post("/comfylock/verify")
    async def _comfylock_verify(request):  # pragma: no cover - needs ComfyUI runtime
        try:
            from comfylock.verify import verify
        except Exception as exc:
            return web.json_response({"error": f"comfylock not installed: {exc}"}, status=500)
        try:
            body = await request.json()
            lock = _lock_from_body(body)
            report = verify(
                lock, comfyui_root=_comfyui_root(),
                check_hashes=bool(body.get("hash", False)),
            )
            return web.json_response({
                "passed": report.passed,
                "errors": report.n_errors,
                "warnings": report.n_warnings,
                "issues": [{"severity": i.severity, "message": i.message} for i in report.issues],
            })
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)

    @_routes.post("/comfylock/inspect")
    async def _comfylock_inspect(request):  # pragma: no cover - needs ComfyUI runtime
        try:
            from comfylock.inspect import inspect_text
        except Exception as exc:
            return web.json_response({"error": f"comfylock not installed: {exc}"}, status=500)
        try:
            body = await request.json()
            lock = _lock_from_body(body)
            return web.json_response({"text": inspect_text(lock)})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)

    @_routes.post("/comfylock/update")
    async def _comfylock_update(request):  # pragma: no cover - needs ComfyUI runtime
        try:
            from comfylock.update import update_lock
        except Exception as exc:
            return web.json_response({"error": f"comfylock not installed: {exc}"}, status=500)
        try:
            body = await request.json()
            lock = _lock_from_body(body)
            _new, changes = update_lock(
                lock, _comfyui_root(),
                do_nodes=True, do_models=False, do_params=False,
            )
            return web.json_response({"changes": changes})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)

except Exception:
    # Not inside ComfyUI (or aiohttp/server unavailable): import is a no-op.
    pass
