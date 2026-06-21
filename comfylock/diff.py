"""`diff` - semantic comparison of two lockfiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model import Lockfile


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


def _model_hash_summary(models, name) -> str:
    for m in models:
        if m.name == name and m.hashes:
            h = m.hashes[0]
            return f"{h.type}:{h.hash[:10]}"
    return "?"


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
            oh = _model_hash_summary([om], name)
            nh = _model_hash_summary([nm], name)
            if oh != nh:
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
