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
        lock = Lockfile(models=[Model("m.safetensors", url="https://h/m.safetensors")])
        with tempfile.TemporaryDirectory() as td:
            res = unpack(lock, td, dry_run=True)
            self.assertEqual(len(res.actions), 1)
            self.assertEqual(res.actions[0].kind, "download")
            self.assertFalse(res.actions[0].done)

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
