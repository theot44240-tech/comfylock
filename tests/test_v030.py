"""Unit tests for the v0.3.0 feature set (offline, no network)."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from comfylock import __version__, fetcher, serialize
from comfylock.completions import SHELLS, completion_script
from comfylock.exporters import FORMATS, export
from comfylock.exporters.json_schema import LOCK_SCHEMA, to_json_schema
from comfylock.exporters.manager_snapshot import (
    from_manager_snapshot,
)
from comfylock.gc import find_orphans, referenced_basenames
from comfylock.hashes import compute
from comfylock.init import candidate_roots, run_init
from comfylock.inspect import human_size, inspect_json, inspect_text
from comfylock.manager_import import manager_import
from comfylock.merge import MergeConflict, merge_locks
from comfylock.model import SCHEMA_VERSION, Hash, Lockfile, Model
from comfylock.pack import StrictError, build_lock
from comfylock.sign import gpg_available, sign_lock, verify_signature
from comfylock.unpack import unpack
from comfylock.update import update_lock


def _git_ok() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Schema v2
# --------------------------------------------------------------------------- #
class SchemaV2Tests(unittest.TestCase):
    def test_default_schema_is_v2(self):
        self.assertEqual(SCHEMA_VERSION, 2)

    def test_v2_model_fields_round_trip(self):
        m = Model(
            "x.safetensors",
            url="https://h/x",
            mirrors=["hf://a/b/x.safetensors", "https://mirror/x"],
            hashes=[Hash("SHA256", "a" * 64)],
            type="lora",
            size=123,
            civitai_model_id=11,
            civitai_version_id=22,
            hf_repo_id="a/b",
            hf_filename="x.safetensors",
        )
        lock = Lockfile(models=[m], comfylock_version="0.3.0",
                        provenance={"os": "linux"}, thumbnail="QkM=")
        again = serialize.loads(serialize.dumps_json(lock))
        rm = again.models[0]
        self.assertEqual(rm.mirrors, ["hf://a/b/x.safetensors", "https://mirror/x"])
        self.assertEqual(rm.civitai_model_id, 11)
        self.assertEqual(rm.civitai_version_id, 22)
        self.assertEqual(rm.hf_repo_id, "a/b")
        self.assertEqual(rm.hf_filename, "x.safetensors")
        self.assertEqual(again.comfylock_version, "0.3.0")
        self.assertEqual(again.provenance, {"os": "linux"})
        self.assertEqual(again.thumbnail, "QkM=")

    def test_v1_lock_omits_v2_fields(self):
        m = Model("x", mirrors=["https://m"], hf_repo_id="a/b", civitai_model_id=1)
        lock = Lockfile(models=[m], version=1, comfylock_version="0.3.0",
                        provenance={"os": "linux"}, thumbnail="QkM=")
        d = lock.to_dict()
        self.assertEqual(d["version"], 1)
        self.assertNotIn("comfylock_version", d)
        self.assertNotIn("provenance", d)
        self.assertNotIn("thumbnail", d)
        self.assertNotIn("mirrors", d["models"][0])
        self.assertNotIn("hf_repo_id", d["models"][0])
        self.assertNotIn("civitai_model_id", d["models"][0])

    def test_v1_lock_still_reads(self):
        v1 = '{"version":1,"models":[{"name":"m","hashes":[{"type":"SHA256","hash":"%s"}]}]}' % ("a" * 64)
        lock = serialize.loads(v1)
        self.assertEqual(lock.version, 1)
        self.assertEqual(lock.models[0].name, "m")

    def test_garbage_v2_fields_degrade(self):
        lock = serialize.loads(json.dumps({
            "version": 2,
            "models": [{"name": "m", "mirrors": "oops", "civitai_model_id": "abc",
                        "hf_repo_id": 5}],
            "provenance": [1, 2],
        }))
        m = lock.models[0]
        self.assertEqual(m.mirrors, [])
        self.assertIsNone(m.civitai_model_id)
        self.assertIsNone(m.hf_repo_id)
        self.assertEqual(lock.provenance, {})

    def test_urls_orders_primary_then_mirrors(self):
        m = Model("m", url="https://a", mirrors=["https://b", "https://a", "https://c"])
        self.assertEqual(m.urls(), ["https://a", "https://b", "https://c"])

    def test_model_urls_empty_when_no_url(self):
        self.assertEqual(Model("m").urls(), [])


class PackV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "models" / "checkpoints").mkdir(parents=True)
        (self.root / "models" / "checkpoints" / "m.safetensors").write_bytes(b"X" * 64)
        self.wf = {"nodes": [{"widgets_values": ["m.safetensors"]}]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_pack_default_is_v2_with_tool_version(self):
        lock = build_lock(self.wf, "w", self.root, hash_types=["SHA256"])
        self.assertEqual(lock.version, 2)
        self.assertEqual(lock.comfylock_version, __version__)

    def test_pack_lock_version_1(self):
        lock = build_lock(self.wf, "w", self.root, hash_types=["SHA256"], lock_version=1)
        self.assertEqual(lock.version, 1)
        self.assertIsNone(lock.comfylock_version)
        self.assertNotIn("comfylock_version", lock.to_dict())

    def test_provenance_opt_in(self):
        without = build_lock(self.wf, "w", self.root, hash_types=["SHA256"])
        self.assertEqual(without.provenance, {})
        withp = build_lock(self.wf, "w", self.root, hash_types=["SHA256"], provenance=True)
        self.assertIn("python", withp.provenance)

    def test_strict_passes_when_present(self):
        lock = build_lock(self.wf, "w", self.root, hash_types=["SHA256"], strict=True)
        self.assertTrue(lock.models[0].present)

    def test_strict_raises_on_missing(self):
        wf = {"nodes": [{"widgets_values": ["missing.safetensors"]}]}
        with self.assertRaises(StrictError):
            build_lock(wf, "w", self.root, hash_types=["SHA256"], strict=True)

    def test_non_strict_records_missing(self):
        wf = {"nodes": [{"widgets_values": ["missing.safetensors"]}]}
        lock = build_lock(wf, "w", self.root, hash_types=["SHA256"])
        self.assertFalse(lock.models[0].present)


# --------------------------------------------------------------------------- #
# inspect
# --------------------------------------------------------------------------- #
class InspectTests(unittest.TestCase):
    def setUp(self):
        self.lock = serialize.read(Path(__file__).resolve().parents[1] / "examples" / "workflow.lock")

    def test_human_size(self):
        self.assertEqual(human_size(None), "?")
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(1000), "1.00 KB")
        self.assertTrue(human_size(6938040682).endswith("GB"))

    def test_inspect_text_has_sections(self):
        out = inspect_text(self.lock)
        for token in ("ComfyLock", "COMFYUI CORE", "CUSTOM NODES", "MODELS",
                      "PARAMETERS", "LOCKFILE", "schema version  2"):
            self.assertIn(token, out)

    def test_inspect_text_lists_models(self):
        out = inspect_text(self.lock)
        self.assertIn("sd_xl_base_1.0.safetensors", out)
        self.assertIn("detail_tweaker_xl.safetensors", out)

    def test_inspect_json_round_trips(self):
        text = inspect_json(self.lock)
        self.assertEqual(serialize.loads(text).to_dict(), self.lock.to_dict())

    def test_inspect_color_wraps_ansi(self):
        self.assertIn("\033[", inspect_text(self.lock, color=True))
        self.assertNotIn("\033[", inspect_text(self.lock, color=False))


# --------------------------------------------------------------------------- #
# exporters
# --------------------------------------------------------------------------- #
class ExportTests(unittest.TestCase):
    def setUp(self):
        self.lock = serialize.read(Path(__file__).resolve().parents[1] / "examples" / "workflow.lock")

    def test_all_formats_non_empty(self):
        for fmt in FORMATS:
            self.assertTrue(export(self.lock, fmt).strip(), fmt)

    def test_unknown_format_raises(self):
        with self.assertRaises(RuntimeError):
            export(self.lock, "nope")

    def test_markdown_has_models_and_links(self):
        md = export(self.lock, "markdown")
        self.assertIn("## Models", md)
        self.assertIn("sd_xl_base_1.0.safetensors", md)
        self.assertIn("https://civitai.com", md)

    def test_dockerfile_pins_core_and_nodes(self):
        df = export(self.lock, "dockerfile")
        self.assertIn("FROM comfyanonymous/comfyui", df)
        self.assertIn(self.lock.comfyui, df)
        self.assertIn("git clone", df)
        self.assertIn(f'comfylock.version="{__version__}"', df)

    def test_json_schema_is_valid_json_and_matches_source(self):
        text = to_json_schema()
        self.assertEqual(json.loads(text), LOCK_SCHEMA)

    def test_manager_snapshot_shape(self):
        snap = json.loads(export(self.lock, "manager-snapshot"))
        self.assertEqual(snap["comfyui"], self.lock.comfyui)
        url = "https://github.com/ltdrdata/ComfyUI-Impact-Pack.git"
        self.assertIn(url, snap["git_custom_nodes"])
        self.assertFalse(snap["git_custom_nodes"][url]["disabled"])

    def test_manager_snapshot_round_trip(self):
        snap = json.loads(export(self.lock, "manager-snapshot"))
        back, warnings = from_manager_snapshot(snap)
        self.assertEqual(back.git_nodes, self.lock.git_nodes)
        self.assertEqual(back.comfyui, self.lock.comfyui)
        self.assertTrue(warnings)

    def test_from_manager_snapshot_rejects_non_dict(self):
        with self.assertRaises(RuntimeError):
            from_manager_snapshot([1, 2, 3])


class ManagerImportTests(unittest.TestCase):
    def test_import_writes_lock(self):
        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "snapshot.json"
            snap.write_text(json.dumps({
                "comfyui": "abc123",
                "git_custom_nodes": {"https://github.com/a/b.git": {"hash": "d" * 40, "disabled": False}},
                "file_custom_nodes": [{"filename": "n.py", "disabled": False}],
            }), encoding="utf-8")
            out, warnings = manager_import(snap)
            lock = serialize.read(out)
            self.assertEqual(lock.comfyui, "abc123")
            self.assertIn("https://github.com/a/b.git", lock.git_nodes)
            self.assertEqual(lock.comfylock_version, __version__)
            self.assertTrue(warnings)

    def test_import_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            manager_import("does-not-exist.json")


# --------------------------------------------------------------------------- #
# gc
# --------------------------------------------------------------------------- #
class GcTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        ck = self.root / "models" / "checkpoints"
        ck.mkdir(parents=True)
        (ck / "used.safetensors").write_bytes(b"U" * 100)
        (ck / "orphan.safetensors").write_bytes(b"O" * 50)
        (ck / "notes.txt").write_text("not a model", encoding="utf-8")
        self.locks = Path(self.tmp.name) / "locks"
        self.locks.mkdir()
        lock = Lockfile(models=[Model("used.safetensors",
                                      paths=["models/checkpoints/used.safetensors"])])
        serialize.write(lock, self.locks / "a.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def test_orphan_detected(self):
        res = find_orphans(self.root, locks_dir=self.locks)
        names = {o.path.name for o in res.orphans}
        self.assertIn("orphan.safetensors", names)
        self.assertNotIn("used.safetensors", names)
        self.assertNotIn("notes.txt", names)  # non-model extension ignored

    def test_total_bytes(self):
        res = find_orphans(self.root, locks_dir=self.locks)
        self.assertEqual(res.total_bytes, 50)
        self.assertEqual(res.scanned_locks, 1)

    def test_referenced_basenames(self):
        names, n = referenced_basenames(self.locks)
        self.assertIn("used.safetensors", names)
        self.assertEqual(n, 1)

    def test_render_no_orphans(self):
        empty = find_orphans(self.root, locks_dir=Path(self.tmp.name) / "nolocks")
        # no locks dir -> everything is an orphan; check the populated render path
        self.assertIn("Orphaned", empty.render())


# --------------------------------------------------------------------------- #
# merge
# --------------------------------------------------------------------------- #
class MergeTests(unittest.TestCase):
    def _lock(self, url, commit, model_hash="a" * 64):
        return Lockfile(
            git_nodes={url: commit},
            models=[Model("m.safetensors", hashes=[Hash("SHA256", model_hash)])],
        )

    def test_union_non_conflicting(self):
        a = Lockfile(git_nodes={"https://x.git": "a" * 40})
        b = Lockfile(git_nodes={"https://y.git": "b" * 40})
        merged, warnings = merge_locks([a, b])
        self.assertEqual(set(merged.git_nodes), {"https://x.git", "https://y.git"})
        self.assertFalse(warnings)

    def test_node_conflict_first_keeps_first(self):
        a = self._lock("https://x.git", "a" * 40)
        b = self._lock("https://x.git", "b" * 40)
        merged, warnings = merge_locks([a, b], strategy="first")
        self.assertEqual(merged.git_nodes["https://x.git"], "a" * 40)
        self.assertTrue(warnings)

    def test_node_conflict_strict_raises(self):
        a = self._lock("https://x.git", "a" * 40)
        b = self._lock("https://x.git", "b" * 40)
        with self.assertRaises(MergeConflict):
            merge_locks([a, b], strategy="strict")

    def test_model_conflict_detected(self):
        a = self._lock("https://x.git", "a" * 40, model_hash="a" * 64)
        b = self._lock("https://x.git", "a" * 40, model_hash="b" * 64)
        with self.assertRaises(MergeConflict):
            merge_locks([a, b], strategy="strict")

    def test_same_model_no_conflict(self):
        a = self._lock("https://x.git", "a" * 40)
        b = self._lock("https://x.git", "a" * 40)
        merged, warnings = merge_locks([a, b], strategy="strict")
        self.assertEqual(len(merged.models), 1)
        self.assertFalse(warnings)

    def test_parameters_dropped(self):
        a = Lockfile(parameters={"seed": 1})
        merged, _ = merge_locks([a])
        self.assertEqual(merged.parameters, {})

    def test_empty_raises(self):
        with self.assertRaises(RuntimeError):
            merge_locks([])

    def test_unknown_strategy(self):
        with self.assertRaises(RuntimeError):
            merge_locks([Lockfile()], strategy="bogus")


# --------------------------------------------------------------------------- #
# completions
# --------------------------------------------------------------------------- #
class CompletionsTests(unittest.TestCase):
    def test_all_shells_non_empty_with_commands(self):
        for shell in SHELLS:
            script = completion_script(shell)
            self.assertTrue(script.strip(), shell)
            self.assertIn("pack", script)
            self.assertIn("verify", script)

    def test_bash_defines_complete(self):
        self.assertIn("complete -F", completion_script("bash"))

    def test_powershell_registers_completer(self):
        self.assertIn("Register-ArgumentCompleter", completion_script("powershell"))

    def test_unknown_shell_raises(self):
        with self.assertRaises(RuntimeError):
            completion_script("tcsh")


# --------------------------------------------------------------------------- #
# fetcher
# --------------------------------------------------------------------------- #
class FetcherTests(unittest.TestCase):
    def test_detect_origin(self):
        self.assertEqual(fetcher.detect_origin("hf://a/b/c"), "huggingface")
        self.assertEqual(fetcher.detect_origin("https://huggingface.co/a"), "huggingface")
        self.assertEqual(fetcher.detect_origin("https://hf.co/a"), "huggingface")
        self.assertEqual(fetcher.detect_origin("https://civitai.com/api/x"), "civitai")
        self.assertEqual(fetcher.detect_origin("file:///x"), "file")
        self.assertEqual(fetcher.detect_origin("https://example.com/x"), "http")

    def test_hf_uri_rewrites_to_https(self):
        self.assertEqual(
            fetcher.prepare_url("hf://org/repo/sub/file.safetensors"),
            "https://huggingface.co/org/repo/resolve/main/sub/file.safetensors",
        )

    def test_civitai_token_injected(self):
        with mock.patch.dict(os.environ, {"CIVITAI_API_KEY": "SECRET"}):
            out = fetcher.prepare_url("https://civitai.com/api/download/models/1")
        self.assertIn("token=SECRET", out)

    def test_civitai_no_token_unchanged(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            url = "https://civitai.com/api/download/models/1"
            self.assertEqual(fetcher.prepare_url(url), url)

    def test_download_file_url(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src.bin"
            src.write_bytes(b"payload" * 100)
            dest = Path(td) / "out" / "dest.bin"
            used = fetcher.download([src.resolve().as_uri()], dest, progress=False)
            self.assertEqual(dest.read_bytes(), src.read_bytes())
            self.assertTrue(used.startswith("file:"))

    def test_download_mirror_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / "good.bin"
            good.write_bytes(b"ok")
            bad = (Path(td) / "missing.bin").resolve().as_uri()
            dest = Path(td) / "d.bin"
            used = fetcher.download([bad, good.resolve().as_uri()], dest, progress=False)
            self.assertEqual(dest.read_bytes(), b"ok")
            self.assertEqual(used, good.resolve().as_uri())

    def test_download_all_fail_raises(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "d.bin"
            bad = (Path(td) / "nope.bin").resolve().as_uri()
            with self.assertRaises(RuntimeError):
                fetcher.download([bad], dest, progress=False)

    def test_download_empty_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                fetcher.download([], Path(td) / "d.bin")


# --------------------------------------------------------------------------- #
# unpack --jobs (parallel) with mirrors
# --------------------------------------------------------------------------- #
class UnpackParallelTests(unittest.TestCase):
    def test_parallel_downloads_all_verify(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "root"
            root.mkdir()
            models = []
            for i in range(3):
                src = Path(td) / f"s{i}.bin"
                src.write_bytes(bytes([i]) * 64 + str(i).encode())
                models.append(Model(
                    f"m{i}.bin", url=src.resolve().as_uri(),
                    paths=[f"models/loras/m{i}.bin"],
                    hashes=[Hash("SHA256", compute(src, "SHA256"))]))
            res = unpack(Lockfile(models=models), root, dry_run=False, jobs=3)
            self.assertEqual(res.errors, 0)
            for i in range(3):
                self.assertTrue((root / f"models/loras/m{i}.bin").exists())

    def test_mirror_used_when_primary_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "root"
            root.mkdir()
            good = Path(td) / "good.bin"
            good.write_bytes(b"REAL" * 16)
            bad = (Path(td) / "gone.bin").resolve().as_uri()
            m = Model("m.bin", url=bad, mirrors=[good.resolve().as_uri()],
                      paths=["models/loras/m.bin"],
                      hashes=[Hash("SHA256", compute(good, "SHA256"))])
            res = unpack(Lockfile(models=[m]), root, dry_run=False)
            self.assertEqual(res.errors, 0)
            self.assertEqual((root / "models/loras/m.bin").read_bytes(), good.read_bytes())


# --------------------------------------------------------------------------- #
# update
# --------------------------------------------------------------------------- #
class UpdateTests(unittest.TestCase):
    def test_update_models_rehashes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ck = root / "models" / "checkpoints"
            ck.mkdir(parents=True)
            f = ck / "m.safetensors"
            f.write_bytes(b"v1" * 64)
            lock = build_lock({"nodes": [{"widgets_values": ["m.safetensors"]}]},
                              "w", root, hash_types=["SHA256"])
            old_hash = lock.models[0].hash_of("SHA256")
            f.write_bytes(b"v2-changed" * 64)
            new, changes = update_lock(lock, root, do_nodes=False, do_models=True, do_params=False)
            self.assertNotEqual(new.models[0].hash_of("SHA256"), old_hash)
            self.assertTrue(any("m.safetensors" in c for c in changes))

    def test_update_no_change_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ck = root / "models" / "checkpoints"
            ck.mkdir(parents=True)
            f = ck / "m.safetensors"
            f.write_bytes(b"stable" * 64)
            lock = build_lock({"nodes": [{"widgets_values": ["m.safetensors"]}]},
                              "w", root, hash_types=["SHA256"])
            _, changes = update_lock(lock, root, do_nodes=False, do_models=True, do_params=False)
            self.assertEqual(changes, [])

    @unittest.skipUnless(_git_ok(), "git required")
    def test_update_nodes_bumps_commit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            node = root / "custom_nodes" / "Node"
            node.mkdir(parents=True)
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
            subprocess.run(["git", "init", "-q"], cwd=node, check=True, env=env)
            (node / "a.py").write_text("1", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=node, check=True, env=env)
            subprocess.run(["git", "commit", "-qm", "1"], cwd=node, check=True, env=env)
            subprocess.run(["git", "remote", "add", "origin", "https://github.com/a/Node.git"],
                           cwd=node, check=True, env=env)
            c1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=node,
                                capture_output=True, text=True, env=env).stdout.strip()
            lock = Lockfile(git_nodes={"https://github.com/a/Node.git": c1})
            (node / "b.py").write_text("2", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=node, check=True, env=env)
            subprocess.run(["git", "commit", "-qm", "2"], cwd=node, check=True, env=env)
            new, changes = update_lock(lock, root, do_nodes=True, do_models=False, do_params=False)
            self.assertNotEqual(new.git_nodes["https://github.com/a/Node.git"], c1)
            self.assertTrue(changes)


# --------------------------------------------------------------------------- #
# sign (graceful paths; full gpg round-trip is environment-dependent)
# --------------------------------------------------------------------------- #
class SignTests(unittest.TestCase):
    def test_gpg_available_is_bool(self):
        self.assertIsInstance(gpg_available(), bool)

    def test_verify_missing_signature(self):
        with tempfile.TemporaryDirectory() as td:
            lock = Path(td) / "w.lock"
            lock.write_text("{}", encoding="utf-8")
            ok, msg = verify_signature(lock)
            self.assertFalse(ok)
            self.assertIn("no signature", msg.lower())

    def test_sigstore_requires_extra(self):
        with tempfile.TemporaryDirectory() as td:
            lock = Path(td) / "w.lock"
            lock.write_text("{}", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                sign_lock(lock, sigstore=True)

    def test_sign_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            sign_lock("nope.lock")


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #
class InitTests(unittest.TestCase):
    def test_candidate_roots(self):
        roots = candidate_roots()
        self.assertTrue(all(isinstance(p, Path) for p in roots))
        self.assertTrue(any(p.name == "ComfyUI" for p in roots))

    def test_non_interactive_returns_2(self):
        fake = mock.Mock()
        fake.isatty.return_value = False
        with mock.patch("sys.stdin", fake):
            self.assertEqual(run_init(), 2)


if __name__ == "__main__":
    unittest.main()
