"""Self-contained, offline self-test: builds a fake ComfyUI env and exercises
pack -> write/read round-trip -> verify (pass) -> mutate -> verify (fail) -> diff.

Run with ``comfy-lock selftest`` or ``python -m comfylock selftest``.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from . import serialize
from .diff import diff as diff_locks
from .hashes import HashCache, compute
from .model import Lockfile, Model
from .pack import build_lock
from .unpack import unpack
from .verify import verify


class _Checker:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def check(self, cond: bool, label: str) -> None:
        if cond:
            self.passed += 1
        else:
            self.failed += 1
            print(f"  FAIL: {label}")


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _init_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    import os
    e = {**os.environ, **env}
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, env=e)
    (path / "node.py").write_text("# node\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=e)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True, env=e)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/example/SomeNode.git"],
        cwd=path, check=True, env=e,
    )
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path,
                         capture_output=True, text=True, env=e)
    return out.stdout.strip()


def _build_env(root: Path) -> dict:
    has_git = _git_available()
    comfy_commit = None
    node_commit = None
    if has_git:
        comfy_commit = _init_repo(root)
        node_commit = _init_repo(root / "custom_nodes" / "SomeNode")
    # file node
    (root / "custom_nodes").mkdir(parents=True, exist_ok=True)
    (root / "custom_nodes" / "my_custom_node.py").write_text("# file node\n", encoding="utf-8")
    # model
    model_dir = root / "models" / "checkpoints"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "model.safetensors"
    model_path.write_bytes(b"MODEL-BYTES-v1" * 100)
    # workflow (UI graph format) referencing the model + params
    workflow = {
        "nodes": [
            {"type": "CheckpointLoaderSimple",
             "widgets_values": ["model.safetensors"]},
            {"type": "KSampler",
             "inputs": [
                 {"name": "seed", "widget": {"value": 42}},
                 {"name": "steps", "widget": {"value": 20}},
                 {"name": "sampler_name", "widget": {"value": "euler"}},
                 {"name": "scheduler", "widget": {"value": "normal"}},
             ]},
        ]
    }
    wf_path = root / "wf.flow.json"
    wf_path.write_text(json.dumps(workflow), encoding="utf-8")
    return {
        "has_git": has_git,
        "comfy_commit": comfy_commit,
        "node_commit": node_commit,
        "model_path": model_path,
        "workflow": workflow,
        "wf_path": wf_path,
    }


def run_selftest() -> int:
    c = _Checker()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "ComfyUI"
        env = _build_env(root)

        lock = build_lock(env["workflow"], "wf.flow.json", root, hash_types=["SHA256", "AutoV2"])

        # --- pack content ---
        c.check(len(lock.models) == 1, "one model extracted")
        m = lock.models[0]
        c.check(m.name == "model.safetensors", "model name")
        c.check(m.present, "model present")
        sha = compute(env["model_path"], "SHA256")
        c.check(m.hash_of("SHA256") == sha, "model sha256 matches")
        c.check(m.hash_of("AutoV2") == sha[:10], "model autov2 matches")
        c.check(m.size == env["model_path"].stat().st_size, "model size recorded")
        c.check(lock.parameters.get("seed") == 42, "param seed")
        c.check(lock.parameters.get("sampler_name") == "euler", "param sampler")

        if env["has_git"]:
            c.check(lock.comfyui == env["comfy_commit"], "comfyui commit")
            c.check(
                "https://github.com/example/SomeNode.git" in lock.git_nodes,
                "git node recorded",
            )
        c.check(
            any(f.filename == "my_custom_node.py" for f in lock.file_nodes),
            "file node recorded",
        )

        # --- write/read round-trip (JSON) ---
        lock_path = root / "wf.lock"
        serialize.write(lock, lock_path)
        reloaded = serialize.read(lock_path)
        c.check(reloaded.to_dict() == lock.to_dict(), "JSON round-trip stable")

        # --- verify passes on the same env ---
        rep = verify(lock, root, cache=HashCache())
        c.check(rep.passed, "verify passes on matching env")
        c.check(rep.n_errors == 0, "verify no errors")

        # --- mutate the model: verify must fail ---
        env["model_path"].write_bytes(b"MODEL-BYTES-v2-TAMPERED" * 100)
        rep2 = verify(lock, root, cache=HashCache())
        c.check(not rep2.passed, "verify fails after tamper")
        c.check(rep2.n_errors >= 1, "verify reports the hash error")

        # --- diff: change a param and a hash ---
        new_lock = serialize.read(lock_path)
        new_lock.parameters["steps"] = 50
        new_lock.models[0].hashes[0].hash = "deadbeef" * 8
        d = diff_locks(lock, new_lock)
        joined = d.render()
        c.check("steps: 20 -> 50" in joined, "diff detects param change")
        c.check("hash" in joined.lower(), "diff detects hash change")

        # --- diff of identical locks is empty ---
        c.check(diff_locks(lock, serialize.read(lock_path)).empty, "diff identical empty")

        # --- reproducible pack via SOURCE_DATE_EPOCH ---
        import os as _os

        _os.environ["SOURCE_DATE_EPOCH"] = "1700000000"
        try:
            r1 = build_lock(env["workflow"], "wf.flow.json", root, hash_types=["SHA256"])
            r2 = build_lock(env["workflow"], "wf.flow.json", root, hash_types=["SHA256"])
            c.check(
                serialize.dumps_json(r1) == serialize.dumps_json(r2),
                "SOURCE_DATE_EPOCH makes pack byte-reproducible",
            )
            c.check(
                r1.generated == "2023-11-14T22:13:20Z",
                "SOURCE_DATE_EPOCH timestamp honoured",
            )
        finally:
            _os.environ.pop("SOURCE_DATE_EPOCH", None)

        # --- invalid hash type is rejected (not silently substituted) ---
        try:
            build_lock(env["workflow"], "wf", root, hash_types=["MD5"])
            c.check(False, "unknown hash type rejected")
        except RuntimeError:
            c.check(True, "unknown hash type rejected")

        # --- ambiguous model basename is detected deterministically ---
        from .scan import locate_models

        dup = Path(td) / "dupcheck"
        (dup / "models" / "a").mkdir(parents=True)
        (dup / "models" / "b").mkdir(parents=True)
        (dup / "models" / "a" / "dup.safetensors").write_bytes(b"1")
        (dup / "models" / "b" / "dup.safetensors").write_bytes(b"2")
        loc = locate_models(dup, ["dup.safetensors"])
        c.check("dup.safetensors" in loc.ambiguous, "ambiguous basename detected")
        c.check(
            loc.found["dup.safetensors"].parent.name == "a",
            "ambiguous match resolved deterministically",
        )

        # --- unpack confines writes to the root (untrusted lockfile) ---
        src = Path(td) / "payload.bin"
        src.write_bytes(b"x" * 64)
        src_url = src.resolve().as_uri()
        unpack_root = Path(td) / "unpack_root"
        unpack_root.mkdir()
        evil = Lockfile(models=[Model("evil", url=src_url, paths=["../../escaped.bin"])])
        ev_res = unpack(evil, unpack_root, dry_run=False)
        c.check(ev_res.errors >= 1, "unpack refuses path traversal")
        c.check(
            not (unpack_root.parent.parent / "escaped.bin").exists(),
            "unpack writes nothing above the root",
        )
        good = Lockfile(models=[Model("ok", url=src_url, paths=["models/loras/ok.bin"])])
        gd_res = unpack(good, unpack_root, dry_run=False)
        c.check(
            gd_res.errors == 0 and (unpack_root / "models/loras/ok.bin").exists(),
            "unpack still writes safe relative paths",
        )

        # --- malformed lockfile yields a clean error, not a traceback ---
        bad = Path(td) / "bad.lock"
        bad.write_text("{not valid json", encoding="utf-8")
        try:
            serialize.read(bad)
            c.check(False, "malformed lockfile raises")
        except RuntimeError:
            c.check(True, "malformed lockfile raises")

    total = c.passed + c.failed
    print(f"selftest: {c.passed}/{total} checks passed.")
    return 0 if c.failed == 0 else 1
