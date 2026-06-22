"""`diff` - semantic comparison of two lockfiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model import Lockfile, Model


@dataclass
class Diff:
    changes: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.changes.append(msg)

    @property
    def empty(self) -> bool:
        return not self.changes

    def render(self) -> str:
        if self.empty:
            return "No differences."
        return "\n".join(f"- {c}" for c in self.changes)


def _short(commit: str) -> str:
    return commit[:10] if commit else "?"


# Strongest first: picks which hash to *display* when two locks differ.
_HASH_DISPLAY_PRIORITY = ("SHA256", "BLAKE3", "BLAKE2B", "AUTOV2", "AUTOV1", "CRC32")


def _hash_map(model: Model) -> dict[str, str]:
    """Map a model's recorded hashes as ``TYPE(upper) -> full hex digest``.

    Keyed by type so the two locks are compared like-for-like, and the value is
    the *full* digest (never a prefix) so the equality test below can't be fooled
    by a short collision.
    """
    return {h.type.upper(): h.hash for h in model.hashes if h.type and h.hash}


def _hash_display(hm: dict[str, str], full: bool = False) -> str:
    def fmt(t: str, v: str) -> str:
        return f"{t}:{v if full else v[:10]}"

    for t in _HASH_DISPLAY_PRIORITY:
        if t in hm:
            return fmt(t, hm[t])
    for t, v in hm.items():  # any non-standard type the lock happened to carry
        return fmt(t, v)
    return "?"


def _model_hash_changed(old: Model, new: Model) -> bool:
    """True when two models' recorded hashes indicate different content.

    Compares hashes of the *same* type (matched by name, full digest). This
    avoids two failure modes of comparing only the first-listed hash's 10-char
    prefix:

    * A real content change whose new digest happens to share its first 10 hex
      chars with the old one was reported as *no change* (40-bit prefix is
      brute-forceable, so a swapped model could slip past ``diff --exit-code``).
    * The *same* model recorded with a different hash-type order -- e.g.
      ``AutoV2``-first vs ``SHA256``-first, and ``AutoV2`` is literally the first
      10 hex of ``SHA256`` -- was reported as a *phantom* change.

    When the two locks share no comparable hash type, the displayed (strongest)
    hash is compared so a wholesale algorithm swap is still surfaced rather than
    silently dropped.
    """
    a, b = _hash_map(old), _hash_map(new)
    common = a.keys() & b.keys()
    if common:
        return any(a[t] != b[t] for t in common)
    if not a and not b:
        return False
    return _hash_display(a) != _hash_display(b)


def diff(old: Lockfile, new: Lockfile) -> Diff:
    d = Diff()

    if old.version != new.version:
        d.add(f"Schema version: {old.version} -> {new.version}")

    if (old.comfyui or "") != (new.comfyui or ""):
        d.add(f"ComfyUI: {_short(old.comfyui or '')} -> {_short(new.comfyui or '')}")

    # Git custom nodes
    old_git, new_git = old.git_nodes, new.git_nodes
    for url in sorted(set(old_git) | set(new_git)):
        if url not in old_git:
            d.add(f"Node added: {url} @ {_short(new_git[url])}")
        elif url not in new_git:
            d.add(f"Node removed: {url}")
        elif old_git[url] != new_git[url]:
            d.add(f"Node {url}: {_short(old_git[url])} -> {_short(new_git[url])}")

    # File custom nodes
    old_files = {f.filename: f for f in old.file_nodes}
    new_files = {f.filename: f for f in new.file_nodes}
    for fn in sorted(set(old_files) | set(new_files)):
        if fn not in old_files:
            d.add(f"File node added: {fn}")
        elif fn not in new_files:
            d.add(f"File node removed: {fn}")
        elif old_files[fn].disabled != new_files[fn].disabled:
            state = "disabled" if new_files[fn].disabled else "enabled"
            d.add(f"File node {fn}: now {state}")

    # Models (match by name)
    old_models = {m.name: m for m in old.models}
    new_models = {m.name: m for m in new.models}
    for name in sorted(set(old_models) | set(new_models), key=str.lower):
        if name not in old_models:
            d.add(f"Model added: {name}")
        elif name not in new_models:
            d.add(f"Model removed: {name}")
        else:
            om, nm = old_models[name], new_models[name]
            if _model_hash_changed(om, nm):
                om_map, nm_map = _hash_map(om), _hash_map(nm)
                oh, nh = _hash_display(om_map), _hash_display(nm_map)
                if oh == nh:  # truncated forms collide: show full digests
                    oh, nh = _hash_display(om_map, full=True), _hash_display(nm_map, full=True)
                d.add(f"Model {name} hash: {oh} -> {nh}")
            if (om.url or "") != (nm.url or ""):
                d.add(f"Model {name} url changed")

    # Parameters
    _diff_params(d, old.parameters, new.parameters)
    return d


def _diff_params(d: Diff, old: dict[str, Any], new: dict[str, Any]) -> None:
    for k in sorted(set(old) | set(new)):
        if k not in old:
            d.add(f"Parameter added: {k} = {new[k]}")
        elif k not in new:
            d.add(f"Parameter removed: {k}")
        elif old[k] != new[k]:
            d.add(f"Parameter {k}: {old[k]} -> {new[k]}")
