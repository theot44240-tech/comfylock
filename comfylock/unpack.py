"""`unpack` - fetch missing custom nodes and models to recreate the environment.

Network operations are explicit and can be previewed with ``dry_run=True``.
Downloads use urllib, so ``file://`` URLs work for offline/testing scenarios.
"""

from __future__ import annotations

import re
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


# A pinned commit is always a git object name: hex, 7-64 chars (sha1=40,
# sha256=64). Refusing anything else stops an untrusted lock from smuggling an
# option (e.g. a value starting with "-") into ``git checkout``.
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")

# Standard git transports. ext::/fd:: remote helpers run arbitrary commands and
# a leading "-" is an option-injection vector, so an untrusted lockfile's repo
# URL must match one of these explicit forms before it is handed to ``git``.
_URL_SCHEME_RE = re.compile(r"^(https?|git|ssh|file)://", re.IGNORECASE)
_SCP_URL_RE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:")


def _safe_clone_url(url: str) -> bool:
    """True if ``url`` is a transport we trust to pass to ``git clone``."""
    if not url or url.startswith("-"):
        return False
    return bool(_URL_SCHEME_RE.match(url) or _SCP_URL_RE.match(url))


def _safe_commit(commit: str) -> bool:
    return bool(_COMMIT_RE.match(commit))


def _within(root: Path, candidate: Path) -> bool:
    """True only if ``candidate`` is a strict descendant of ``root``.

    A lockfile is untrusted (it is shared between machines, like a freeze
    file), so any path it supplies must be confined under ``comfyui_root``.
    ``resolve`` collapses ``..`` and follows symlinks, so this rejects both
    traversal (``../../x``) and absolute paths (``/etc/x``, ``C:\\x``).
    """
    root_res = root.resolve()
    return root_res in candidate.resolve().parents


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
        if not _safe_clone_url(url):
            result.actions.append(
                Action("skip", url, "unsafe repo url", error="unsafe url")
            )
            continue
        if not _safe_commit(commit):
            result.actions.append(
                Action("skip", url, f"unsafe commit ref: {commit}", error="unsafe commit")
            )
            continue
        node_dir = _node_dir_for(root, url)
        if not _within(root, node_dir):
            result.actions.append(
                Action("skip", url, "unsafe node path", error="unsafe path")
            )
            continue
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
        dest = root / p
        if _within(root, dest) and dest.exists():
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
    if not _within(root, root / dest):
        return Action("skip", m.name, f"unsafe path: {dest}", error="unsafe path")
    return Action("download", m.name, f"{m.url} -> {dest}")


def _do_clone(url: str, node_dir: Path, commit: str, act: Action) -> None:
    node_dir.parent.mkdir(parents=True, exist_ok=True)
    # ``--`` ends option parsing so a URL can never be read as a git option
    # (e.g. ``--upload-pack=<cmd>``); the caller has already allow-listed it.
    if git(["clone", "--", url, str(node_dir)], node_dir.parent) is None:
        act.error = "clone failed"
        return
    _do_checkout(node_dir, commit, act)


def _do_checkout(node_dir: Path, commit: str, act: Action) -> None:
    if git(["fetch", "--all"], node_dir) is None:
        act.error = "fetch failed"
        return
    # ``commit`` is hex-validated by the caller; ``--`` is belt-and-braces so it
    # can never be parsed as an option or pathspec.
    if git(["checkout", commit, "--"], node_dir) is None:
        act.error = f"checkout {commit[:10]} failed"
        return
    act.done = True


def _do_download(root: Path, m: Model, act: Action) -> None:
    if not m.url:
        act.error = "no url"
        return
    url = m.url
    dest = root / (m.paths[0] if m.paths else _default_dest(m))
    if not _within(root, dest):  # defense in depth; _plan_model already filters
        act.error = "unsafe path"
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        # file:// is intentional (offline/testing, see module docstring); the
        # written path is confined to the root by _within above, and the result
        # is integrity-checked against the lock's hash below.
        urllib.request.urlretrieve(url, dest)  # noqa: S310
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
