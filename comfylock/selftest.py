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
from .model import Hash, Lockfile, Model
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

        # --- diff compares the FULL digest, matched by type ---
        # A real change whose new SHA256 shares the old digest's first 10 hex
        # chars must still be detected (the gate compares full digests, not a
        # brute-forceable 40-bit prefix).
        coll_old = Lockfile(models=[Model("m", hashes=[Hash("SHA256", "abcdef0123" + "0" * 54)])])
        coll_new = Lockfile(models=[Model("m", hashes=[Hash("SHA256", "abcdef0123" + "f" * 54)])])
        c.check(
            not diff_locks(coll_old, coll_new).empty,
            "diff detects a change behind a shared 10-hex prefix",
        )
        # The same model recorded AutoV2-first vs SHA256-first (AutoV2 == first
        # 10 hex of SHA256) must NOT show a phantom change.
        _sha = "a" * 64
        order_a = Lockfile(models=[Model("m", hashes=[Hash("AutoV2", _sha[:10]), Hash("SHA256", _sha)])])
        order_b = Lockfile(models=[Model("m", hashes=[Hash("SHA256", _sha), Hash("AutoV2", _sha[:10])])])
        c.check(
            diff_locks(order_a, order_b).empty,
            "diff ignores hash-type ordering for identical content",
        )

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

        # --- verify prefers the lock's recorded path over a basename collision ---
        # A same-named decoy in an earlier-sorting subdir must not be hashed in
        # place of the genuinely pinned file (false mismatch / artifact masking).
        prefroot = Path(td) / "prefer"
        (prefroot / "models" / "loras").mkdir(parents=True)
        (prefroot / "models" / "loras" / "x.safetensors").write_bytes(b"PINNED" * 50)
        pref_lock = build_lock(
            {"nodes": [{"widgets_values": ["x.safetensors"]}]},
            "w.json", prefroot, hash_types=["SHA256"],
        )
        c.check(verify(pref_lock, prefroot).passed, "verify passes on the pinned file")
        (prefroot / "models" / "checkpoints").mkdir(parents=True)
        (prefroot / "models" / "checkpoints" / "x.safetensors").write_bytes(b"DECOY")
        c.check(
            verify(pref_lock, prefroot).passed,
            "verify checks the recorded path, not the earlier-sorting decoy",
        )

        # --- unpack confines writes to the root (untrusted lockfile) ---
        src = Path(td) / "payload.bin"
        src.write_bytes(b"x" * 64)
        src_url = src.resolve().as_uri()
        src_sha = compute(src, "SHA256")
        unpack_root = Path(td) / "unpack_root"
        unpack_root.mkdir()
        evil = Lockfile(models=[Model(
            "evil", url=src_url, paths=["../../escaped.bin"],
            hashes=[Hash("SHA256", src_sha)])])
        ev_res = unpack(evil, unpack_root, dry_run=False)
        c.check(ev_res.errors >= 1, "unpack refuses path traversal")
        c.check(
            not (unpack_root.parent.parent / "escaped.bin").exists(),
            "unpack writes nothing above the root",
        )
        good = Lockfile(models=[Model(
            "ok", url=src_url, paths=["models/loras/ok.bin"],
            hashes=[Hash("SHA256", src_sha)])])
        gd_res = unpack(good, unpack_root, dry_run=False)
        c.check(
            gd_res.errors == 0 and (unpack_root / "models/loras/ok.bin").exists(),
            "unpack still writes safe relative paths",
        )
        # A URL with no recomputable hash is unverifiable: refuse it and write
        # nothing (an untrusted lock must not drop unchecked bytes in models/).
        nohash = Lockfile(models=[Model(
            "nohash", url=src_url, paths=["models/loras/nohash.bin"])])
        nh_res = unpack(nohash, unpack_root, dry_run=False)
        c.check(
            nh_res.errors >= 1 and not (unpack_root / "models/loras/nohash.bin").exists(),
            "unpack refuses an unverifiable (hash-less) download",
        )

        # --- verify confines untrusted git-node URLs to the root ---
        # A node URL's last path segment becomes a directory name; ``..`` (or a
        # UNC/rooted segment on Windows) must not let verify probe outside
        # custom_nodes/ (existence oracle / NTLM leak). Reported missing instead.
        vroot = Path(td) / "verify_root"
        (vroot / "custom_nodes").mkdir(parents=True)
        escaped = Lockfile(git_nodes={"https://e/x/..": "a" * 40})
        vrep = verify(escaped, vroot)
        c.check(
            "Node missing" in vrep.render() and "not a git repo" not in vrep.render(),
            "verify refuses an out-of-root git-node path",
        )

        # --- integrity gate: a weak-only hash cannot certify a download ---
        # An untrusted lock that pins only a forgeable hash (AutoV2 = 40-bit
        # prefix of SHA256) must not be fetched; a strong hash still downloads.
        weakroot = Path(td) / "weak_root"
        weakroot.mkdir()
        weak = Lockfile(models=[Model(
            "weak.bin", url=src_url, paths=["models/loras/weak.bin"],
            hashes=[Hash("AutoV2", compute(src, "AutoV2"))])])
        wk_res = unpack(weak, weakroot, dry_run=False)
        c.check(
            wk_res.errors >= 1 and not (weakroot / "models/loras/weak.bin").exists(),
            "unpack refuses a weak-only (forgeable hash) download",
        )

        # --- AutoV1 no longer collapses small files to one constant ---
        sa = Path(td) / "av1_a.bin"
        sb = Path(td) / "av1_b.bin"
        sa.write_bytes(b"AAAA" * 8)
        sb.write_bytes(b"BBBB" * 9)
        c.check(
            compute(sa, "AutoV1") != compute(sb, "AutoV1"),
            "AutoV1 distinguishes distinct small files (no empty-window constant)",
        )

        # --- diff: SHA256 vs its derived AutoV2 is not a phantom change ---
        _s = "abcd012345" + "0" * 54
        c.check(
            diff_locks(
                Lockfile(models=[Model("m", hashes=[Hash("SHA256", _s)])]),
                Lockfile(models=[Model("m", hashes=[Hash("AutoV2", _s[:10])])]),
            ).empty,
            "diff reconciles SHA256 with its derived AutoV2 (no phantom change)",
        )

        # --- malformed lockfile yields a clean error, not a traceback ---
        bad = Path(td) / "bad.lock"
        bad.write_text("{not valid json", encoding="utf-8")
        try:
            serialize.read(bad)
            c.check(False, "malformed lockfile raises")
        except RuntimeError:
            c.check(True, "malformed lockfile raises")

        # --- a non-UTF-8 lockfile is a clean error, not a UnicodeDecodeError ---
        # read_text(utf-8) raises UnicodeDecodeError (a ValueError) on binary bytes;
        # the CLI handler catches only RuntimeError/OSError, so it escaped as a
        # traceback. read() must convert it to a RuntimeError.
        nonutf8 = Path(td) / "nonutf8.lock"
        nonutf8.write_bytes(b'{"version":1,\xff\xfe"models":[]}')
        try:
            serialize.read(nonutf8)
            c.check(False, "non-UTF-8 lockfile raises a clean error")
        except RuntimeError:
            c.check(True, "non-UTF-8 lockfile raises a clean error")
        except UnicodeDecodeError:
            c.check(False, "non-UTF-8 lockfile raises a clean error")

        # --- an infinite numeric field coerces instead of crashing ---
        # JSON ``1e400`` parses to float inf; ``int(inf)`` raises OverflowError
        # (not the ValueError/TypeError the coercion caught) -> traceback on
        # verify/diff. The field must degrade to None.
        inflock = serialize.loads('{"version":1,"models":[{"name":"x","size":1e400}]}')
        c.check(
            len(inflock.models) == 1 and inflock.models[0].size is None,
            "infinite size coerces to None (no OverflowError)",
        )

        # ----------------------------------------------------------------- #
        # v0.3.0 features
        # ----------------------------------------------------------------- #
        from .completions import SHELLS, completion_script
        from .exporters import FORMATS, export
        from .exporters.json_schema import LOCK_SCHEMA, to_json_schema
        from .exporters.manager_snapshot import from_manager_snapshot
        from .fetcher import detect_origin, download, prepare_url
        from .gc import find_orphans
        from .inspect import inspect_text
        from .merge import MergeConflict, merge_locks
        from .model import SCHEMA_VERSION

        c.check(SCHEMA_VERSION == 2, "default schema is v2")

        # --- v2 model fields round-trip; v1 output omits them ---
        v2model = Model(
            "x.safetensors", url="https://h/x", mirrors=["hf://a/b/x"],
            hashes=[Hash("SHA256", "a" * 64)], hf_repo_id="a/b",
            civitai_model_id=7,
        )
        v2lock = Lockfile(models=[v2model], comfylock_version="0.3.0", version=2)
        rt = serialize.loads(serialize.dumps_json(v2lock))
        c.check(
            rt.models[0].mirrors == ["hf://a/b/x"]
            and rt.models[0].hf_repo_id == "a/b"
            and rt.models[0].civitai_model_id == 7
            and rt.comfylock_version == "0.3.0",
            "v2 model + lock fields round-trip",
        )
        v1dict = Lockfile(models=[v2model], version=1, comfylock_version="0.3.0").to_dict()
        c.check(
            "comfylock_version" not in v1dict and "mirrors" not in v1dict["models"][0],
            "v1 output omits v2-only fields",
        )
        c.check(
            v2model.urls() == ["https://h/x", "hf://a/b/x"],
            "Model.urls() lists primary then mirrors",
        )

        # --- pack --strict ---
        from .pack import StrictError
        from .pack import build_lock as _bl

        strict_wf = {"nodes": [{"widgets_values": ["absent.safetensors"]}]}
        try:
            _bl(strict_wf, "w", root, hash_types=["SHA256"], strict=True)
            c.check(False, "pack --strict rejects a missing model")
        except StrictError:
            c.check(True, "pack --strict rejects a missing model")

        # --- inspect ---
        ins = inspect_text(lock)
        c.check(
            "MODELS" in ins and "model.safetensors" in ins,
            "inspect renders the model section",
        )

        # --- export: all formats non-empty; json-schema matches source ---
        c.check(
            all(export(lock, f).strip() for f in FORMATS),
            "every export format emits output",
        )
        c.check(json.loads(to_json_schema()) == LOCK_SCHEMA, "json-schema export is valid")

        # --- manager-snapshot round-trip ---
        snap_lock = Lockfile(
            comfyui="abc123",
            git_nodes={"https://github.com/a/b.git": "d" * 40},
        )
        from .exporters import to_manager_snapshot

        snap = json.loads(to_manager_snapshot(snap_lock))
        back, _w = from_manager_snapshot(snap)
        c.check(
            back.comfyui == "abc123" and "https://github.com/a/b.git" in back.git_nodes,
            "manager snapshot round-trips nodes + commit",
        )

        # --- merge: conflict detection under strict ---
        ma = Lockfile(git_nodes={"https://x.git": "a" * 40})
        mb = Lockfile(git_nodes={"https://x.git": "b" * 40})
        merged_first, mw = merge_locks([ma, mb], strategy="first")
        c.check(
            merged_first.git_nodes["https://x.git"] == "a" * 40 and bool(mw),
            "merge --strategy first keeps the first pin and warns",
        )
        try:
            merge_locks([ma, mb], strategy="strict")
            c.check(False, "merge --strategy strict raises on conflict")
        except MergeConflict:
            c.check(True, "merge --strategy strict raises on conflict")

        # --- gc: orphan detection ---
        gcroot = Path(td) / "gcroot"
        (gcroot / "models" / "checkpoints").mkdir(parents=True)
        (gcroot / "models" / "checkpoints" / "keep.safetensors").write_bytes(b"K" * 10)
        (gcroot / "models" / "checkpoints" / "drop.safetensors").write_bytes(b"D" * 10)
        gclocks = Path(td) / "gclocks"
        gclocks.mkdir()
        serialize.write(
            Lockfile(models=[Model("keep.safetensors",
                                   paths=["models/checkpoints/keep.safetensors"])]),
            gclocks / "a.lock",
        )
        gcres = find_orphans(gcroot, locks_dir=gclocks)
        orphan_names = {o.path.name for o in gcres.orphans}
        c.check(
            "drop.safetensors" in orphan_names and "keep.safetensors" not in orphan_names,
            "gc identifies the unreferenced model only",
        )

        # --- completions: every shell emits a non-empty script ---
        c.check(
            all("pack" in completion_script(s) for s in SHELLS),
            "completions emitted for every shell",
        )

        # --- fetcher: origin detection + civitai token + mirror fallback ---
        c.check(
            detect_origin("hf://a/b/c") == "huggingface"
            and detect_origin("https://civitai.com/x") == "civitai"
            and prepare_url("hf://o/r/f.safetensors")
            == "https://huggingface.co/o/r/resolve/main/f.safetensors",
            "fetcher detects origins and rewrites hf://",
        )
        fsrc = Path(td) / "fetch_src.bin"
        fsrc.write_bytes(b"FETCH" * 20)
        fdest = Path(td) / "fetch_dest" / "out.bin"
        bad_uri = (Path(td) / "fetch_missing.bin").resolve().as_uri()
        used = download([bad_uri, fsrc.resolve().as_uri()], fdest, progress=False)
        c.check(
            fdest.exists() and fdest.read_bytes() == fsrc.read_bytes()
            and used == fsrc.resolve().as_uri(),
            "fetcher falls back from a bad URL to a working mirror",
        )

        # ----------------------------------------------------------------- #
        # v0.4.0 features
        # ----------------------------------------------------------------- #
        import hashlib as _hl

        from .audit import audit_lock, parse_github_repo
        from .doctor import doctor as run_doctor
        from .jsonout import Result, status_for

        # --- audit: GitHub owner/repo parsing, non-GitHub skipped ---
        c.check(
            parse_github_repo("https://github.com/o/r.git") == ("o", "r")
            and parse_github_repo("git@github.com:o/r.git") == ("o", "r")
            and parse_github_repo("https://gitlab.com/o/r.git") is None,
            "audit parses GitHub owner/repo and skips non-GitHub hosts",
        )

        # --- audit: injected fetch reports advisories; empty list = none ---
        alock = Lockfile(git_nodes={
            "https://github.com/acme/vuln.git": "a" * 40,
            "https://github.com/acme/clean.git": "b" * 40,
        })

        def _fake_fetch(owner: str, repo: str) -> list:
            if repo == "vuln":
                return [{"ghsa_id": "GHSA-1", "severity": "high",
                         "summary": "x", "cve_id": "CVE-1", "html_url": "http://x"}]
            return []

        ares = audit_lock(alock, fetch=_fake_fetch)
        c.check(
            ares.has_advisories and ares.advisory_count == 1,
            "audit reports an advisory from the fetcher",
        )
        c.check(
            any(n.repo == "clean" and not n.advisories and not n.error for n in ares.nodes),
            "audit handles an empty advisory list correctly",
        )

        # --- audit: a fetch error degrades to a warning, not a crash ---
        def _boom(owner: str, repo: str) -> list:
            raise RuntimeError("network down")

        bres = audit_lock(
            Lockfile(git_nodes={"https://github.com/a/b.git": "c" * 40}), fetch=_boom
        )
        c.check(
            len(bres.warnings) == 1 and not bres.has_advisories,
            "audit degrades a fetch error to a warning",
        )

        # --- hash command parity with stdlib ---
        hf = Path(td) / "hashme.bin"
        hf.write_bytes(b"comfylock-hash-check" * 7)
        c.check(
            compute(hf, "SHA256") == _hl.sha256(hf.read_bytes()).hexdigest(),
            "hash command matches stdlib sha256",
        )

        # --- export: shell verifies each model; requirements pins git+ ---
        shlock = Lockfile(models=[Model(
            "m.safetensors", url="https://h/m",
            paths=["models/checkpoints/m.safetensors"],
            hashes=[Hash("SHA256", "a" * 64)],
        )])
        sh = export(shlock, "shell")
        c.check(
            "sha256sum" in sh and sh.startswith("#!/usr/bin/env bash"),
            "export --format shell verifies each model with sha256sum",
        )
        reqlock = Lockfile(git_nodes={"https://github.com/a/b.git": "d" * 40})
        c.check(
            ("git+https://github.com/a/b@" + "d" * 40) in export(reqlock, "requirements"),
            "export --format requirements emits a git+ pin",
        )
        c.check(
            "git_custom_nodes" in export(Lockfile(comfyui="abc123"), "manager-snapshot"),
            "export --format manager-snapshot includes git_custom_nodes",
        )
        # A lock is untrusted input and the shell/dockerfile exports are executed:
        # a `;`-injected commit must stay shell-quoted, never a bare command.
        inj_sh = export(Lockfile(comfyui="aaaa; touch PWNED #"), "shell")
        c.check(
            "git checkout 'aaaa; touch PWNED #'" in inj_sh
            and "git checkout aaaa; touch" not in inj_sh,
            "export --format shell quotes injected lock values",
        )
        inj_df = export(
            Lockfile(git_nodes={"https://github.com/a/b.git": "d\nRUN touch PWNED"}),
            "dockerfile",
        )
        c.check(
            not any(ln.strip() == "RUN touch PWNED" for ln in inj_df.splitlines()),
            "export --format dockerfile blocks newline instruction breakout",
        )

        # --- doctor: a clean fake install passes; a missing root errors ---
        droot = Path(td) / "comfy_install"
        (droot / "models" / "checkpoints").mkdir(parents=True)
        (droot / "custom_nodes").mkdir(parents=True)
        (droot / "main.py").write_text("# comfy\n", encoding="utf-8")
        c.check(run_doctor(str(droot)).n_errors == 0, "doctor passes a valid install")
        c.check(
            run_doctor(str(Path(td) / "nope")).n_errors >= 1,
            "doctor errors on a missing root",
        )

        # --- json envelope: status + required fields ---
        c.check(
            status_for([], []) == "ok"
            and status_for([], ["w"]) == "warning"
            and status_for(["e"], []) == "error",
            "json envelope status derives from errors/warnings",
        )
        env = Result("verify", "ok", {"passed": True}).envelope()
        c.check(
            env["command"] == "verify" and env["status"] == "ok" and "version" in env,
            "json envelope carries command/status/version",
        )

    total = c.passed + c.failed
    print(f"selftest: {c.passed}/{total} checks passed.")
    return 0 if c.failed == 0 else 1
