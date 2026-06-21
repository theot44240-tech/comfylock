"""ComfyLock ComfyUI extension.

Drop this ``panel`` folder into ``ComfyUI/custom_nodes/`` (or symlink it) and
install the ``comfylock`` package (``pip install comfylock``). It adds a
"Save Lockfile" button to the ComfyUI menu that pins the current graph's models,
custom-node commits, and key parameters into a ``.lock`` file.

The extension registers an HTTP route ``POST /comfylock/pack`` on ComfyUI's
aiohttp server. All imports are guarded so importing this module outside of a
running ComfyUI (e.g. during tests or linting) never raises.
"""

from __future__ import annotations

import os

# ComfyUI looks for these two module-level names in every custom node.
NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]


def _comfyui_root() -> str:
    # ComfyUI runs from its repo root; fall back to CWD.
    return os.environ.get("COMFYUI_ROOT") or os.getcwd()


try:  # Only succeeds inside a running ComfyUI process.
    from aiohttp import web  # type: ignore
    from server import PromptServer  # type: ignore

    @PromptServer.instance.routes.post("/comfylock/pack")
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

except Exception:
    # Not inside ComfyUI (or aiohttp/server unavailable): import is a no-op.
    pass
