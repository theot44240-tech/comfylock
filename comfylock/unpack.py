"""`unpack` - fetch missing custom nodes and models to recreate the environment.

Network operations are explicit and can be previewed with ``dry_run=True``.
Downloads use urllib, so ``file://`` URLs work for offline/testing scenarios.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .hashes import COMPUTABLE, compute
from .model import Lockfile, Model
from .scan import git, head_commit, is_git_repo


@dataclass
class Action:
    kind: str  # "clone" | "checkout" | "download" | "skip"
    target: str
    detail: str = ""
    done: bool = False
    error: str | None = None

    def render(self) -> str:
        status = "DRY" if not self.done and self.error is None else (
            "ERR" if self.error else "done"
        )
        line = f"[{status}] {self.kind}: {self.target}"
        if self.detail:
            line += f" ({self.detail})"
        if self.error:
            line += f" -- {self.error}"
        return line


@dataclass
class UnpackResult:
    actions: list[Action] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for a in self.actions if a.error)

    def render(self) -> str:
        if not self.actions:
            return "Nothing to do: environment already satisfies the lock."
        return "\n".join(a.render() for a in self.actions)


# Map a model's recorded ``type`` to its conventional ComfyUI models/ subdir so
# downloads land where ComfyUI (and a later verify) will look for them.
_TYPE_DIRS = {
    "checkpoint": "checkpoints",
    "diffuser": "checkpoints",
    "diffusers": "checkpoints",
    "lora": "loras",
    "locon": "loras",
    "vae": "vae",
    "controlnet": "controlnet",
    "control_net": "controlnet",
    "clip": "clip",
    "clip_vision": "clip_vision",
    "unet": "unet",
    "upscale": "upscale_models",
    "upscale_model": "upscale_models",
    "embedding": "embeddings",
    "embeddings": "embeddings",
    "gligen": "gligen",
    "hypernetwork": "hypernetworks",
}


def _default_dest(m: Model) -> str:
    sub = _TYPE_DIRS.get((m.type or "").lower(), "checkpoints")
    return f"models/{sub}/{Path(m.name).name}"


def _node_dir_for(root: Path, url: str) -> Path:
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return root / "custom_nodes" / name


def unpack(
    lock: Lockfile,
    comfyui_root: str | Path,
    dry_run: bool = True,
    download_models: bool = True,
) -> UnpackResult:
    root = Path(comfyui_root)
    result = UnpackResult()

    # --- Custom git nodes ---
    for url, commit in sorted(lock.git_nodes.items()):
        node_dir = _node_dir_for(root, url)
        if not node_dir.exists():
            act = Action("clone", url, f"-> {node_dir} @ {commit[:10]}")
            if not dry_run:
                _do_clone(url, node_dir, commit, act)
            result.actions.append(act)
        elif is_git_repo(node_dir) and head_commit(node_dir) != commit:
            act = Action("checkout", node_dir.name, f"-> {commit[:10]}")
            if not dry_run:
                _do_checkout(node_dir, commit, act)
            result.actions.append(act)

    # --- Models ---
    if download_models:
        for m in lock.models:
            if not _model_present(root, m):
                mact = _plan_model(root, m)
                if mact is None:
                    continue
                if not dry_run and mact.kind == "download":
                    _do_download(root, m, mact)
                result.actions.append(mact)

    return result


def _model_present(root: Path, m: Model) -> bool:
    for p in m.paths:
        if (root / p).exists():
            return True
    # fall back to basename search under models/
    base = Path(m.name).name
    models_dir = root / "models"
    if models_dir.is_dir():
        for f in models_dir.rglob(base):
            if f.is_file():
                return True
    return False


def _plan_model(root: Path, m: Model) -> Action | None:
    if not m.url:
        return Action("skip", m.name, "no url in lock", error="no url")
    dest = m.paths[0] if m.paths else _default_dest(m)
    return Action("download", m.name, f"{m.url} -> {dest}")


def _do_clone(url: str, node_dir: Path, commit: str, act: Action) -> None:
    node_dir.parent.mkdir(parents=True, exist_ok=True)
    if git(["clone", url, str(node_dir)], node_dir.parent) is None:
        act.error = "clone failed"
        return
    _do_checkout(node_dir, commit, act)


def _do_checkout(node_dir: Path, commit: str, act: Action) -> None:
    if git(["fetch", "--all"], node_dir) is None:
        act.error = "fetch failed"
        return
    if git(["checkout", commit], node_dir) is None:
        act.error = f"checkout {commit[:10]} failed"
        return
    act.done = True


def _do_download(root: Path, m: Model, act: Action) -> None:
    if not m.url:
        act.error = "no url"
        return
    url = m.url
    dest = root / (m.paths[0] if m.paths else _default_dest(m))
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, dest)  # noqa: S310 - url comes from a trusted lock
    except Exception as exc:  # pragma: no cover - network dependent
        act.error = f"download failed: {exc}"
        return
    # Integrity check against the first recomputable hash in the lock.
    for ht in COMPUTABLE:
        expected = m.hash_of(ht)
        if expected:
            actual = compute(dest, ht)
            if actual != expected:
                act.error = f"hash mismatch after download ({ht})"
                return
            break
    act.done = True
