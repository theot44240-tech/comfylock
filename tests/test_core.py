"""Unit tests for the ComfyLock core (offline, no network)."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from comfylock import serialize
from comfylock.diff import diff
from comfylock.hashes import HashCache, compute
from comfylock.model import FileNode, Hash, Lockfile, Model
from comfylock.pack import build_lock
from comfylock.unpack import unpack
from comfylock.verify import verify
from comfylock.workflow import extract_models, extract_params


def _git_ok() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


class HashTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "f.bin"
        self.path.write_bytes(b"hello world" * 1000)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sha256_deterministic(self):
        self.assertEqual(compute(self.path, "SHA256"), compute(self.path, "SHA256"))
        self.assertEqual(len(compute(self.path, "SHA256")), 64)

    def test_autov2_is_sha256_prefix(self):
        self.assertEqual(compute(self.path, "AutoV2"), compute(self.path, "SHA256")[:10])

    def test_crc32_len(self):
        self.assertEqual(len(compute(self.path, "CRC32")), 8)

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            compute(self.path, "MD5")

    def test_cache_hits_and_recomputes(self):
        cache_path = Path(self.tmp.name) / "c.json"
        cache = HashCache(cache_path)
        v1 = cache.get(self.path, "SHA256")
        cache.save()
        cache2 = HashCache(cache_path)
        self.assertEqual(cache2.get(self.path, "SHA256"), v1)
        # mutate -> recompute
        self.path.write_bytes(b"changed")
        self.assertNotEqual(cache2.get(self.path, "SHA256"), v1)


class WorkflowTests(unittest.TestCase):
    def test_extract_models_ui_format(self):
        wf = {"nodes": [{"widgets_values": ["sdxl.safetensors", "lora_a.pt"]}]}
        self.assertEqual(extract_models(wf), ["lora_a.pt", "sdxl.safetensors"])

    def test_extract_models_api_format(self):
        wf = {"1": {"class_type": "X", "inputs": {"ckpt_name": "m.ckpt"}}}
        self.assertEqual(extract_models(wf), ["m.ckpt"])

    def test_ignores_non_models(self):
        wf = {"nodes": [{"widgets_values": ["hello", "euler", "image.png"]}]}
        self.assertEqual(extract_models(wf), [])

    def test_extract_params_api(self):
        wf = {"1": {"inputs": {"seed": 7, "steps": 30, "sampler_name": "dpmpp"}}}
        p = extract_params(wf)
        self.assertEqual(p["seed"], 7)
        self.assertEqual(p["steps"], 30)
        self.assertEqual(p["sampler_name"], "dpmpp")


class SerializeTests(unittest.TestCase):
    def test_round_trip_json(self):
        lock = Lockfile(
            workflow="w.json",
            comfyui="abc123",
            git_nodes={"https://x/y.git": "deadbeef"},
            file_nodes=[FileNode("a.py", False)],
            models=[Model("m.safetensors", url="https://h/m",
                          paths=["models/checkpoints/m.safetensors"],
                          hashes=[Hash("SHA256", "f" * 64)], size=10)],
            parameters={"seed": 1},
        )
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "w.lock"
            serialize.write(lock, p)
            back = serialize.read(p)
            self.assertEqual(back.to_dict(), lock.to_dict())

    def test_loads_detects_json(self):
        text = json.dumps({"version": 1, "models": [{"name": "x"}]})
        lock = serialize.loads(text)
        self.assertEqual(lock.models[0].name, "x")


class PackVerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        mdir = self.root / "models" / "loras"
        mdir.mkdir(parents=True)
        self.model = mdir / "lora.safetensors"
        self.model.write_bytes(b"weights" * 500)
        self.wf = {"nodes": [{"widgets_values": ["lora.safetensors"]}]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_pack_then_verify_pass(self):
        lock = build_lock(self.wf, "w.json", self.root)
        rep = verify(lock, self.root)
        self.assertTrue(rep.passed, rep.render())

    def test_verify_detects_tamper(self):
        lock = build_lock(self.wf, "w.json", self.root)
        self.model.write_bytes(b"tampered")
        rep = verify(lock, self.root)
        self.assertFalse(rep.passed)
        self.assertGreaterEqual(rep.n_errors, 1)

    def test_verify_missing_model(self):
        lock = build_lock(self.wf, "w.json", self.root)
        self.model.unlink()
        rep = verify(lock, self.root)
        self.assertFalse(rep.passed)

    def test_no_root_marks_models_absent(self):
        lock = build_lock(self.wf, "w.json", None)
        self.assertFalse(lock.models[0].present)


class DiffTests(unittest.TestCase):
    def _lock(self, **kw):
        base = dict(comfyui="aaaa", parameters={"steps": 20},
                    models=[Model("m", hashes=[Hash("SHA256", "1" * 64)])])
        base.update(kw)
        return Lockfile(**base)

    def test_param_change(self):
        d = diff(self._lock(), self._lock(parameters={"steps": 50}))
        self.assertIn("steps: 20 -> 50", d.render())

    def test_comfyui_change(self):
        d = diff(self._lock(), self._lock(comfyui="bbbb"))
        self.assertIn("ComfyUI", d.render())

    def test_model_added_removed(self):
        d = diff(self._lock(models=[]), self._lock())
        self.assertIn("Model added: m", d.render())

    def test_identical_empty(self):
        self.assertTrue(diff(self._lock(), self._lock()).empty)


class UnpackTests(unittest.TestCase):
    def test_dry_run_lists_download(self):
        lock = Lockfile(models=[Model(
            "m.safetensors", url="https://h/m.safetensors",
            hashes=[Hash("SHA256", "0" * 64)])])
        with tempfile.TemporaryDirectory() as td:
            res = unpack(lock, td, dry_run=True)
            self.assertEqual(len(res.actions), 1)
            self.assertEqual(res.actions[0].kind, "download")
            self.assertFalse(res.actions[0].done)

    def test_unverifiable_download_is_refused(self):
        # A lock that gives a URL but no recomputable hash must not be fetched:
        # the download would be unverifiable and land in the models tree
        # unchecked. Both the dry-run preview and the apply must fail clean.
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src.safetensors"
            src.write_bytes(b"abc" * 100)
            dest_rel = "models/checkpoints/src.safetensors"
            lock = Lockfile(models=[Model(
                "src.safetensors", url=src.resolve().as_uri(), paths=[dest_rel])])
            root = Path(td) / "ComfyUI"
            root.mkdir()
            preview = unpack(lock, root, dry_run=True)
            self.assertEqual(preview.errors, 1, preview.render())
            self.assertIn("hash", preview.render().lower())
            res = unpack(lock, root, dry_run=False)
            self.assertEqual(res.errors, 1, res.render())
            self.assertFalse((root / dest_rel).exists())

    def test_hash_mismatch_removes_downloaded_file(self):
        # On mismatch the (untrusted) bytes must be removed, not left on disk.
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src.safetensors"
            src.write_bytes(b"abc" * 100)
            dest_rel = "models/checkpoints/src.safetensors"
            lock = Lockfile(models=[Model(
                "src.safetensors", url=src.resolve().as_uri(),
                paths=[dest_rel], hashes=[Hash("SHA256", "0" * 64)])])
            root = Path(td) / "ComfyUI"
            root.mkdir()
            res = unpack(lock, root, dry_run=False)
            self.assertEqual(res.errors, 1, res.render())
            self.assertFalse((root / dest_rel).exists())

    def test_local_file_download_and_verify(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src.safetensors"
            src.write_bytes(b"abc" * 100)
            sha = compute(src, "SHA256")
            url = src.resolve().as_uri()
            lock = Lockfile(models=[Model(
                "src.safetensors", url=url,
                paths=["models/checkpoints/src.safetensors"],
                hashes=[Hash("SHA256", sha)])])
            root = Path(td) / "ComfyUI"
            root.mkdir()
            res = unpack(lock, root, dry_run=False)
            self.assertEqual(res.errors, 0, res.render())
            self.assertTrue((root / "models/checkpoints/src.safetensors").exists())

    def test_download_hash_mismatch_errors(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src.safetensors"
            src.write_bytes(b"abc" * 100)
            url = src.resolve().as_uri()
            lock = Lockfile(models=[Model(
                "src.safetensors", url=url,
                paths=["models/checkpoints/src.safetensors"],
                hashes=[Hash("SHA256", "0" * 64)])])
            root = Path(td) / "ComfyUI"
            root.mkdir()
            res = unpack(lock, root, dry_run=False)
            self.assertEqual(res.errors, 1)


class UnpackPathSafetyTests(unittest.TestCase):
    """A lockfile is untrusted; ``unpack`` must never write outside the root."""

    def _attempt(self, td, bad_path):
        src = Path(td) / "src.safetensors"
        src.write_bytes(b"payload" * 50)
        root = Path(td) / "ComfyUI"
        root.mkdir()
        # A valid hash so a *legit* path actually downloads+verifies; an unsafe
        # path is still refused at plan time, before any download is attempted.
        lock = Lockfile(models=[Model(
            "evil", url=src.resolve().as_uri(), paths=[bad_path],
            hashes=[Hash("SHA256", compute(src, "SHA256"))])])
        return unpack(lock, root, dry_run=False), root

    def test_traversal_path_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            res, root = self._attempt(td, "../../escaped.bin")
            self.assertEqual(res.errors, 1, res.render())
            self.assertIn("unsafe path", res.render())
            # Nothing written above the root.
            self.assertFalse((Path(td) / "escaped.bin").exists())
            self.assertFalse((root.parent / "escaped.bin").exists())

    def test_absolute_path_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "outside.bin"
            res, _ = self._attempt(td, str(target))
            self.assertEqual(res.errors, 1, res.render())
            self.assertFalse(target.exists())

    def test_dry_run_preview_flags_unsafe_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            root.mkdir()
            lock = Lockfile(models=[Model(
                "evil", url="file:///x", paths=["../../escaped.bin"])])
            res = unpack(lock, root, dry_run=True)
            self.assertEqual(res.errors, 1, res.render())
            self.assertIn("unsafe path", res.render())

    def test_legit_relative_path_still_downloads(self):
        with tempfile.TemporaryDirectory() as td:
            res, root = self._attempt(td, "models/loras/ok.safetensors")
            self.assertEqual(res.errors, 0, res.render())
            self.assertTrue((root / "models/loras/ok.safetensors").exists())


class VerifyPathSafetyTests(unittest.TestCase):
    """A lockfile is untrusted; ``verify`` must not stat/hash a file outside the
    root via a lock-supplied ``paths`` entry (absolute or ``../`` traversal)."""

    def _lock_pointing_at(self, root_size_hash, bad_path):
        size, sha = root_size_hash
        return serialize.loads(json.dumps({"version": 1, "models": [{
            "name": "nope.safetensors",
            "paths": [{"path": bad_path}],
            "size": size,
            "hashes": [{"type": "SHA256", "hash": sha}]}]}))

    def test_absolute_path_is_not_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            (root / "models").mkdir(parents=True)
            secret = Path(td) / "secret.bin"
            secret.write_bytes(b"topsecret" * 50)
            # Lock's size+hash match the OUTSIDE file: if verify followed the
            # absolute path it would wrongly report a match. Containment must
            # instead report not-found.
            lock = self._lock_pointing_at(
                (secret.stat().st_size, compute(secret, "SHA256")), str(secret))
            rep = verify(lock, root)
            self.assertFalse(rep.passed)
            self.assertIn("file not found", rep.render())

    def test_traversal_path_is_not_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            (root / "models").mkdir(parents=True)
            secret = Path(td) / "secret.bin"
            secret.write_bytes(b"abc" * 100)
            lock = self._lock_pointing_at(
                (secret.stat().st_size, compute(secret, "SHA256")), "../../secret.bin")
            rep = verify(lock, root)
            self.assertFalse(rep.passed)
            self.assertIn("file not found", rep.render())

    def test_legit_in_root_fallback_path_is_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            mdir = root / "models" / "checkpoints"
            mdir.mkdir(parents=True)
            f = mdir / "actual.safetensors"
            f.write_bytes(b"weights" * 100)
            # Model name's basename differs from the on-disk file, so the models
            # glob does NOT find it; verify must fall back to the (in-root) lock
            # path and still pass. Proves the guard doesn't reject legit paths.
            lock = serialize.loads(json.dumps({"version": 1, "models": [{
                "name": "renamed.safetensors",
                "paths": [{"path": "models/checkpoints/actual.safetensors"}],
                "size": f.stat().st_size,
                "hashes": [{"type": "SHA256", "hash": compute(f, "SHA256")}]}]}))
            rep = verify(lock, root)
            self.assertTrue(rep.passed, rep.render())


class VerifyFileNodeSafetyTests(unittest.TestCase):
    """A lockfile is untrusted; a file-node ``filename`` must not let ``verify``
    stat a path outside the root. An absolute or ``../`` filename would turn
    the present/missing report into a file-existence oracle (does the victim
    have ``~/.ssh/id_rsa``?) and ``.exists()`` on a device/UNC path can hang or
    leak credentials. Mirrors the model-path containment guard above."""

    def _lock_with_filenode(self, filename):
        return serialize.loads(json.dumps({"version": 1, "custom_nodes": {
            "files": [{"filename": filename}]}}))

    def test_absolute_filename_is_not_statted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            (root / "custom_nodes").mkdir(parents=True)
            secret = Path(td) / "secret_node.py"
            secret.write_text("x")  # exists OUTSIDE the root
            rep = verify(self._lock_with_filenode(str(secret)), root)
            self.assertFalse(rep.passed)
            self.assertIn("File node missing", rep.render())
            self.assertNotIn("File node present", rep.render())

    def test_traversal_filename_is_not_statted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            (root / "custom_nodes").mkdir(parents=True)
            secret = Path(td) / "secret_node.py"
            secret.write_text("x")
            rep = verify(self._lock_with_filenode("../../secret_node.py"), root)
            self.assertFalse(rep.passed)
            self.assertIn("File node missing", rep.render())
            self.assertNotIn("File node present", rep.render())

    def test_legit_filename_is_found(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            cn = root / "custom_nodes"
            cn.mkdir(parents=True)
            (cn / "my_node.py").write_text("x")
            rep = verify(self._lock_with_filenode("my_node.py"), root)
            self.assertIn("File node present: my_node.py", rep.render())

    def test_legit_disabled_filename_is_found(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            cn = root / "custom_nodes"
            cn.mkdir(parents=True)
            (cn / "my_node.py.disabled").write_text("x")
            rep = verify(self._lock_with_filenode("my_node.py"), root)
            self.assertIn("File node present: my_node.py", rep.render())


class UnpackGitSafetyTests(unittest.TestCase):
    """A lockfile is untrusted; node URLs/commits must not let it run commands.

    ``git`` has remote-helper transports (``ext::``, ``fd::``) and options
    (``--upload-pack=``) that execute arbitrary commands, so ``unpack`` must
    refuse anything that is not a standard transport + hex commit *before* it
    reaches ``git clone``/``git checkout``.
    """

    def _root(self, td):
        root = Path(td) / "ComfyUI"
        root.mkdir()
        return root

    def test_ext_scheme_url_is_refused_and_runs_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            marker = Path(td) / "pwned"
            lock = Lockfile(git_nodes={f"ext::sh -c touch {marker}": "a" * 40})
            res = unpack(lock, root, dry_run=False)
            self.assertGreaterEqual(res.errors, 1, res.render())
            self.assertIn("unsafe url", res.render())
            self.assertFalse(marker.exists())

    def test_dash_leading_url_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            lock = Lockfile(git_nodes={"--upload-pack=touch x": "b" * 40})
            res = unpack(lock, root, dry_run=False)
            self.assertGreaterEqual(res.errors, 1, res.render())
            self.assertIn("unsafe url", res.render())

    def test_non_hex_commit_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            lock = Lockfile(
                git_nodes={"https://github.com/a/b.git": "--evil-ref"})
            res = unpack(lock, root, dry_run=False)
            self.assertGreaterEqual(res.errors, 1, res.render())
            self.assertIn("unsafe commit", res.render())

    def test_dry_run_preview_flags_unsafe_url(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            lock = Lockfile(git_nodes={"ext::sh -c id": "c" * 40})
            res = unpack(lock, root, dry_run=True)
            self.assertGreaterEqual(res.errors, 1, res.render())
            self.assertIn("unsafe url", res.render())

    def test_legit_https_and_hex_commit_pass_validation(self):
        # A standard transport + hex commit is previewed as a clone with no error
        # (dry run, so no network); proves the guard does not reject real repos.
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            lock = Lockfile(
                git_nodes={"https://github.com/example/Node.git": "d" * 40})
            res = unpack(lock, root, dry_run=True)
            self.assertEqual(res.errors, 0, res.render())
            self.assertEqual(len(res.actions), 1)
            self.assertEqual(res.actions[0].kind, "clone")


class HashTypeValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        mdir = self.root / "models" / "checkpoints"
        mdir.mkdir(parents=True)
        (mdir / "m.safetensors").write_bytes(b"weights" * 100)
        self.wf = {"nodes": [{"widgets_values": ["m.safetensors"]}]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_unknown_hash_type_raises(self):
        with self.assertRaises(RuntimeError):
            build_lock(self.wf, "w.json", self.root, hash_types=["MD5"])

    def test_known_types_are_recorded(self):
        lock = build_lock(self.wf, "w.json", self.root, hash_types=["sha256", "AutoV2"])
        m = lock.models[0]
        self.assertIsNotNone(m.hash_of("SHA256"))
        self.assertIsNotNone(m.hash_of("AutoV2"))

    def test_duplicate_types_collapse(self):
        lock = build_lock(self.wf, "w.json", self.root, hash_types=["SHA256", "sha256"])
        self.assertEqual(len(lock.models[0].hashes), 1)


class DeterminismTests(unittest.TestCase):
    def test_source_date_epoch_reproducible(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mdir = root / "models" / "checkpoints"
            mdir.mkdir(parents=True)
            (mdir / "m.safetensors").write_bytes(b"w" * 256)
            wf = {"nodes": [{"widgets_values": ["m.safetensors"]}]}
            os.environ["SOURCE_DATE_EPOCH"] = "1700000000"
            try:
                a = build_lock(wf, "w.json", root)
                b = build_lock(wf, "w.json", root)
            finally:
                os.environ.pop("SOURCE_DATE_EPOCH", None)
            self.assertEqual(serialize.dumps_json(a), serialize.dumps_json(b))
            self.assertEqual(a.generated, "2023-11-14T22:13:20Z")


class AmbiguousModelTests(unittest.TestCase):
    def test_locate_reports_ambiguity_and_is_deterministic(self):
        from comfylock.scan import locate_models

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "models" / "a").mkdir(parents=True)
            (root / "models" / "b").mkdir(parents=True)
            (root / "models" / "a" / "dup.safetensors").write_bytes(b"1")
            (root / "models" / "b" / "dup.safetensors").write_bytes(b"2")
            loc = locate_models(root, ["dup.safetensors"])
            self.assertIn("dup.safetensors", loc.ambiguous)
            self.assertEqual(loc.found["dup.safetensors"].parent.name, "a")

    def test_verify_warns_on_ambiguity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "models" / "a").mkdir(parents=True)
            (root / "models" / "b").mkdir(parents=True)
            (root / "models" / "a" / "dup.safetensors").write_bytes(b"same")
            (root / "models" / "b" / "dup.safetensors").write_bytes(b"same")
            wf = {"nodes": [{"widgets_values": ["dup.safetensors"]}]}
            lock = build_lock(wf, "w.json", root)
            rep = verify(lock, root)
            self.assertGreaterEqual(rep.n_warnings, 1)
            self.assertIn("several files", rep.render())


class HashCaseInsensitivityTests(unittest.TestCase):
    """Interop locks (Civitai/A1111) store hex digests UPPERCASE; ``compute``
    emits lowercase. Loading must canonicalize so comparison is case-insensitive.
    """

    def test_loads_lowercases_hash(self):
        text = json.dumps({"version": 1, "models": [
            {"name": "m", "hashes": [{"type": "SHA256", "hash": "ABCDEF" + "0" * 58}]}]})
        lock = serialize.loads(text)
        self.assertEqual(lock.models[0].hashes[0].hash, "abcdef" + "0" * 58)

    def test_verify_passes_with_uppercase_locked_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mdir = root / "models" / "checkpoints"
            mdir.mkdir(parents=True)
            f = mdir / "m.safetensors"
            f.write_bytes(b"weights" * 500)
            sha_upper = compute(f, "SHA256").upper()
            text = json.dumps({"version": 1, "models": [{
                "name": "m.safetensors",
                "paths": [{"path": "models/checkpoints/m.safetensors"}],
                "size": f.stat().st_size,
                "hashes": [{"type": "SHA256", "hash": sha_upper}]}]})
            lock = serialize.loads(text)
            rep = verify(lock, root)
            self.assertTrue(rep.passed, rep.render())

    def test_diff_ignores_hash_case(self):
        upper = json.dumps({"version": 1, "models": [
            {"name": "m", "hashes": [{"type": "SHA256", "hash": "A" * 64}]}]})
        lower = json.dumps({"version": 1, "models": [
            {"name": "m", "hashes": [{"type": "SHA256", "hash": "a" * 64}]}]})
        self.assertTrue(diff(serialize.loads(upper), serialize.loads(lower)).empty)


class SchemaCompatTests(unittest.TestCase):
    def test_verify_warns_on_newer_schema(self):
        lock = Lockfile(version=999)
        rep = verify(lock, None)
        self.assertIn("newer than this tool", rep.render())


class SerializeErrorTests(unittest.TestCase):
    def test_malformed_json_raises_runtime_error(self):
        with self.assertRaises(RuntimeError):
            serialize.loads("{ not valid json")

    def test_non_mapping_top_level_raises(self):
        with self.assertRaises(RuntimeError):
            serialize.loads("[1, 2, 3]")

    def test_read_missing_file_raises_filenotfound(self):
        with self.assertRaises(FileNotFoundError):
            serialize.read("does-not-exist.lock")

    def test_read_error_includes_path(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.lock"
            p.write_text("{oops", encoding="utf-8")
            with self.assertRaises(RuntimeError) as ctx:
                serialize.read(p)
            self.assertIn("bad.lock", str(ctx.exception))

    def test_read_workflow_bad_json_raises_runtime_error(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "wf.json"
            p.write_text("{oops", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                serialize.read_workflow(p)


class UnpackDestTests(unittest.TestCase):
    def test_download_routes_by_type(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "lora.safetensors"
            src.write_bytes(b"abc" * 10)
            sha = compute(src, "SHA256")
            lock = Lockfile(models=[Model(
                "lora.safetensors", url=src.resolve().as_uri(), type="lora",
                hashes=[Hash("SHA256", sha)])])
            root = Path(td) / "ComfyUI"
            root.mkdir()
            res = unpack(lock, root, dry_run=False)
            self.assertEqual(res.errors, 0, res.render())
            self.assertTrue((root / "models/loras/lora.safetensors").exists())

    def test_dry_run_dest_reflects_type(self):
        lock = Lockfile(models=[Model(
            "cn.safetensors", url="https://h/cn.safetensors", type="controlnet",
            hashes=[Hash("SHA256", "0" * 64)])])
        with tempfile.TemporaryDirectory() as td:
            res = unpack(lock, td, dry_run=True)
            self.assertIn("models/controlnet/cn.safetensors", res.render())


@unittest.skipUnless(_git_ok(), "git not available")
class GitNodeTests(unittest.TestCase):
    def test_scan_records_node_commit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            node = root / "custom_nodes" / "SomeNode"
            node.mkdir(parents=True)
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
            subprocess.run(["git", "init", "-q"], cwd=node, check=True, env=env)
            (node / "x.py").write_text("x")
            subprocess.run(["git", "add", "-A"], cwd=node, check=True, env=env)
            subprocess.run(["git", "commit", "-qm", "i"], cwd=node, check=True, env=env)
            subprocess.run(["git", "remote", "add", "origin",
                            "https://github.com/example/SomeNode.git"],
                           cwd=node, check=True, env=env)
            from comfylock.scan import scan_custom_nodes
            git_nodes, _ = scan_custom_nodes(root)
            self.assertIn("https://github.com/example/SomeNode.git", git_nodes)


if __name__ == "__main__":
    unittest.main()
