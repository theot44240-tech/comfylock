"""Unit tests for the v0.4.1 surface (offline, no network).

config / progress / sync / enrich / schema-v2 fields / docker-compose export /
extended audit (static checks + SARIF) / pack --annotate/--enrich/--schema-version.
Stdlib ``unittest`` so the CI ``unittest discover`` job (no pytest) runs them too.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from comfylock import audit, cli, config, enrich, serialize, sync
from comfylock.model import FileNode, Hash, Lockfile, Model
from comfylock.pack import build_lock, parse_annotations, workflow_hash
from comfylock.progress import ProgressBar, progress_enabled


def _run_cli(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(argv)
    return rc, buf.getvalue()


@contextlib.contextmanager
def _chdir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
class ConfigTests(unittest.TestCase):
    def test_discovery_walks_ancestors(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "comfylock.toml").write_text(
                '[comfylock]\ncomfyui_root = "/x/ComfyUI"\n', encoding="utf-8"
            )
            sub = root / "a" / "b"
            sub.mkdir(parents=True)
            found = config.find_config(sub)
            self.assertEqual(found, root / "comfylock.toml")

    def test_reads_known_keys_only(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "comfylock.toml"
            p.write_text(
                "[comfylock]\n"
                'comfyui_root = "/home/u/ComfyUI"\n'
                'hash = ["SHA256", "AutoV2"]\n'
                "jobs = 4\n"
                "schema_version = 2\n"
                'unknown_key = "ignored"\n',
                encoding="utf-8",
            )
            cfg = config.read_config_file(p)
            self.assertEqual(cfg["comfyui_root"], "/home/u/ComfyUI")
            self.assertEqual(cfg["hash"], ["SHA256", "AutoV2"])
            self.assertEqual(cfg["jobs"], 4)
            self.assertNotIn("unknown_key", cfg)

    def test_merge_cli_wins(self):
        cfg = {"comfyui_root": "/from/config", "hash": ["AutoV2"]}
        self.assertEqual(config.merge("/from/cli", cfg, "comfyui_root"), "/from/cli")
        self.assertEqual(config.merge(None, cfg, "comfyui_root"), "/from/config")
        # empty list also means "not given"
        self.assertEqual(config.merge([], cfg, "hash"), ["AutoV2"])

    def test_default_hash_alias(self):
        cfg = {"default_hash": ["BLAKE2B"]}
        self.assertEqual(config.merge(None, cfg, "hash"), ["BLAKE2B"])

    def test_minimal_parser_fallback(self):
        # Exercise the pure-Python reader directly (used on Python < 3.11).
        tables = config._parse_minimal(
            "# c\n[comfylock]\nx = 1\ny = true\nz = [\"a\", \"b\"]\ns = \"hi\"  # cmt\n"
        )
        body = tables["comfylock"]
        self.assertEqual(body["x"], 1)
        self.assertIs(body["y"], True)
        self.assertEqual(body["z"], ["a", "b"])
        self.assertEqual(body["s"], "hi")

    def test_tool_comfylock_section(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "comfylock.toml"
            p.write_text('[tool.comfylock]\njobs = 2\n', encoding="utf-8")
            self.assertEqual(config.read_config_file(p).get("jobs"), 2)

    def test_unreadable_config_degrades(self):
        self.assertEqual(config.read_config_file(None), {})
        self.assertEqual(config.read_config_file("/no/such/file.toml"), {})


# --------------------------------------------------------------------------- #
# progress
# --------------------------------------------------------------------------- #
class ProgressTests(unittest.TestCase):
    def test_disabled_in_ci(self):
        with io.StringIO() as s:
            old = os.environ.get("CI")
            os.environ["CI"] = "true"
            try:
                self.assertFalse(progress_enabled(s))
            finally:
                if old is None:
                    os.environ.pop("CI", None)
                else:
                    os.environ["CI"] = old

    def test_bar_render_determinate(self):
        bar = ProgressBar("dl", enabled=False, width=10)
        line = bar.render_line(50, 100)
        self.assertIn("50.0%", line)
        self.assertIn("[#####-----]", line)

    def test_bar_render_spinner(self):
        bar = ProgressBar(enabled=False)
        line = bar.render_line(1234, 0)  # unknown total -> spinner
        self.assertTrue(any(c in line for c in "|/-\\"))

    def test_disabled_bar_is_silent(self):
        s = io.StringIO()
        bar = ProgressBar("x", stream=s, enabled=False)
        bar.update(5, 10)
        bar.finish()
        self.assertEqual(s.getvalue(), "")

    def test_enabled_bar_writes(self):
        s = io.StringIO()
        bar = ProgressBar("x", stream=s, enabled=True)
        bar.update(5, 10)
        bar.finish("done")
        self.assertIn("done", s.getvalue())


# --------------------------------------------------------------------------- #
# sync
# --------------------------------------------------------------------------- #
def _refs(head, extra=None):
    d = {"HEAD": head, "refs/heads/main": head}
    if extra:
        d.update(extra)
    return d


class SyncTests(unittest.TestCase):
    def test_up_to_date(self):
        lock = Lockfile(git_nodes={"https://github.com/a/b.git": "c" * 40})
        _, res = sync.sync(lock, ls_remote=lambda u: _refs("c" * 40))
        self.assertTrue(res.all_current)
        self.assertEqual(res.nodes[0].status, sync.UP_TO_DATE)

    def test_update_available(self):
        lock = Lockfile(git_nodes={"https://github.com/a/b.git": "b" * 40})
        _, res = sync.sync(
            lock, ls_remote=lambda u: _refs("c" * 40, {"refs/heads/old": "b" * 40})
        )
        self.assertEqual(res.nodes[0].status, sync.UPDATE_AVAILABLE)
        self.assertFalse(res.all_current)

    def test_diverged(self):
        lock = Lockfile(git_nodes={"https://github.com/a/b.git": "b" * 40})
        _, res = sync.sync(lock, ls_remote=lambda u: _refs("c" * 40))
        self.assertEqual(res.nodes[0].status, sync.DIVERGED)

    def test_unreachable(self):
        lock = Lockfile(git_nodes={"https://github.com/a/b.git": "b" * 40})
        _, res = sync.sync(lock, ls_remote=lambda u: {})
        self.assertEqual(res.nodes[0].status, sync.UNREACHABLE)
        self.assertTrue(res.all_current)  # unreachable does not fail the gate

    def test_update_nodes_repins(self):
        lock = Lockfile(git_nodes={"https://github.com/a/b.git": "b" * 40})
        new, res = sync.sync(
            lock, ls_remote=lambda u: _refs("c" * 40), update_nodes=True
        )
        self.assertEqual(new.git_nodes["https://github.com/a/b.git"], "c" * 40)
        self.assertEqual(res.updated, 1)
        # input lock is untouched
        self.assertEqual(lock.git_nodes["https://github.com/a/b.git"], "b" * 40)

    def test_unsafe_url_skipped(self):
        lock = Lockfile(git_nodes={"ext::sh -c evil": "b" * 40})
        called = []
        _, res = sync.sync(lock, ls_remote=lambda u: called.append(u) or {})
        self.assertEqual(res.nodes[0].status, sync.UNREACHABLE)
        self.assertEqual(called, [])  # never queried

    def test_cli_check_only_exit_code(self):
        lock = Lockfile(git_nodes={"https://github.com/a/b.git": "b" * 40})
        with tempfile.TemporaryDirectory() as td:
            lp = Path(td) / "w.lock"
            serialize.write(lock, lp)
            import unittest.mock as mock

            with mock.patch(
                "comfylock.sync._git_ls_remote", return_value=_refs("c" * 40)
            ):
                rc, _ = _run_cli(["sync", str(lp), "--check-only"])
        self.assertEqual(rc, 1)


# --------------------------------------------------------------------------- #
# enrich
# --------------------------------------------------------------------------- #
class EnrichTests(unittest.TestCase):
    def test_parse_hf_resolve_url(self):
        url = "https://huggingface.co/org/repo/resolve/main/sub/file.safetensors"
        self.assertEqual(enrich.parse_hf_url(url), ("org/repo", "sub/file.safetensors"))

    def test_parse_hf_scheme(self):
        self.assertEqual(
            enrich.parse_hf_url("hf://org/repo/f.safetensors"),
            ("org/repo", "f.safetensors"),
        )

    def test_parse_civitai_api(self):
        self.assertEqual(
            enrich.parse_civitai_url("https://civitai.com/api/download/models/130072"),
            (None, 130072),
        )

    def test_parse_civitai_web(self):
        self.assertEqual(
            enrich.parse_civitai_url("https://civitai.com/models/4201?modelVersionId=130072"),
            (4201, 130072),
        )

    def test_non_hf_url_is_none(self):
        self.assertIsNone(enrich.parse_hf_url("https://example.com/x"))
        self.assertIsNone(enrich.parse_civitai_url("https://example.com/x"))

    def test_enrich_model_fills_fields(self):
        m = Model("f.safetensors", url="https://huggingface.co/o/r/resolve/main/f.safetensors")
        enrich.enrich_model(m, ["hf"])
        self.assertEqual(m.hf_repo_id, "o/r")
        self.assertEqual(m.hf_filename, "f.safetensors")

    def test_recovery_urls(self):
        m = Model("x", hf_repo_id="o/r", hf_filename="f.bin", civitai_version_id=7)
        urls = enrich.recovery_urls(m)
        self.assertIn("https://huggingface.co/o/r/resolve/main/f.bin", urls)
        self.assertIn("https://civitai.com/api/download/models/7", urls)

    def test_download_candidates_dedup_order(self):
        m = Model("x", url="https://primary/x", mirrors=["https://m/x"],
                  hf_repo_id="o/r", hf_filename="f.bin")
        cands = enrich.download_candidates(m)
        self.assertEqual(cands[0], "https://primary/x")
        self.assertIn("https://huggingface.co/o/r/resolve/main/f.bin", cands)

    def test_resolve_sources_validation(self):
        self.assertEqual(enrich.resolve_sources(["hf"]), ["hf"])
        self.assertEqual(sorted(enrich.resolve_sources(["all"])), ["civitai", "hf"])
        with self.assertRaises(RuntimeError):
            enrich.resolve_sources(["bogus"])


# --------------------------------------------------------------------------- #
# schema v2 fields
# --------------------------------------------------------------------------- #
class SchemaV2Tests(unittest.TestCase):
    def test_new_fields_round_trip(self):
        lock = Lockfile(
            version=2,
            workflow_hash="sha256:" + "a" * 64,
            environment={"python": "3.12.0", "platform": "linux"},
            annotations={"author": "me", "tags": ["portrait", "sdxl"]},
            pip_requirements=["torch==2.1.0", "numpy"],
        )
        rt = serialize.loads(serialize.dumps_json(lock))
        self.assertEqual(rt.workflow_hash, "sha256:" + "a" * 64)
        self.assertEqual(rt.environment["platform"], "linux")
        self.assertEqual(rt.annotations["tags"], ["portrait", "sdxl"])
        self.assertEqual(rt.pip_requirements, ["numpy", "torch==2.1.0"])

    def test_v1_omits_new_fields(self):
        d = Lockfile(
            version=1, workflow_hash="sha256:x", environment={"python": "3"},
            annotations={"a": 1}, pip_requirements=["x"],
        ).to_dict()
        self.assertNotIn("workflow_hash", d)
        self.assertNotIn("environment", d)
        self.assertNotIn("annotations", d)
        self.assertNotIn("pip", d.get("custom_nodes", {}))

    def test_from_dict_tolerates_garbage(self):
        lock = serialize.loads(json.dumps({
            "version": 2,
            "workflow_hash": ["not", "a", "string"],
            "environment": "nope",
            "annotations": 42,
            "custom_nodes": {"pip": "notalist"},
        }))
        self.assertIsNone(lock.workflow_hash)
        self.assertEqual(lock.environment, {})
        self.assertEqual(lock.annotations, {})
        self.assertEqual(lock.pip_requirements, [])

    def test_copy_is_independent(self):
        lock = Lockfile(git_nodes={"u": "c"}, annotations={"a": 1})
        c = lock.copy()
        c.git_nodes["u"] = "d"
        c.annotations["a"] = 2
        self.assertEqual(lock.git_nodes["u"], "c")
        self.assertEqual(lock.annotations["a"], 1)


# --------------------------------------------------------------------------- #
# docker-compose export
# --------------------------------------------------------------------------- #
class DockerComposeTests(unittest.TestCase):
    def test_structure(self):
        lock = Lockfile(
            comfyui="abc123",
            git_nodes={"https://github.com/a/b.git": "d" * 40},
            models=[Model("m.safetensors", paths=["models/loras/m.safetensors"])],
        )
        from comfylock.exporters import export

        text = export(lock, "docker-compose")
        self.assertIn("services:", text)
        self.assertIn("comfyui:", text)
        self.assertIn("./models:/ComfyUI/models", text)
        self.assertIn("models/loras", text)

    def test_injection_quoted(self):
        from comfylock.exporters import export

        text = export(
            Lockfile(git_nodes={"https://github.com/a/b.git": "d\nRUN evil"}),
            "docker-compose",
        )
        # a newline-injected commit must not become its own top-level line
        self.assertFalse(any(ln.strip() == "RUN evil" for ln in text.splitlines()))


# --------------------------------------------------------------------------- #
# extended audit (static + SARIF)
# --------------------------------------------------------------------------- #
class StaticAuditTests(unittest.TestCase):
    def _lock(self):
        return Lockfile(
            git_nodes={"http://1.2.3.4/x/Node.git": "a" * 40},
            file_nodes=[FileNode(filename="../escape.py")],
            models=[
                Model("weak.safetensors", url="http://h.xyz/m",
                      paths=["../out.bin"], hashes=[Hash("CRC32", "deadbeef")], size=500),
            ],
        )

    def test_all_categories_fire(self):
        findings = audit.static_audit(self._lock())
        ids = {f.rule_id for f in findings}
        self.assertIn("node-url-http", ids)
        self.assertIn("node-url-ip", ids)
        self.assertIn("model-url-http", ids)
        self.assertIn("model-url-tld", ids)
        self.assertIn("hash-weak", ids)
        self.assertIn("path-traversal", ids)
        self.assertIn("node-path", ids)
        self.assertIn("size-small", ids)

    def test_clean_lock_no_findings(self):
        clean = Lockfile(
            git_nodes={"https://github.com/a/b.git": "a" * 40},
            models=[Model("m.safetensors", url="https://huggingface.co/o/r/resolve/main/m.safetensors",
                          paths=["models/loras/m.safetensors"],
                          hashes=[Hash("SHA256", "a" * 64)], size=5_000_000)],
        )
        self.assertEqual(audit.static_audit(clean), [])

    def test_sarif_shape(self):
        doc = json.loads(audit.to_sarif(audit.static_audit(self._lock())))
        self.assertEqual(doc["version"], "2.1.0")
        run = doc["runs"][0]
        self.assertEqual(run["tool"]["driver"]["name"], "comfylock")
        self.assertTrue(run["results"])
        self.assertIn("ruleId", run["results"][0])

    def test_cli_strict_exit(self):
        with tempfile.TemporaryDirectory() as td:
            lp = Path(td) / "w.lock"
            serialize.write(self._lock(), lp)
            rc, _ = _run_cli(["audit", str(lp), "--no-advisories", "--strict"])
        self.assertEqual(rc, 1)

    def test_cli_sarif_format(self):
        with tempfile.TemporaryDirectory() as td:
            lp = Path(td) / "w.lock"
            serialize.write(self._lock(), lp)
            rc, out = _run_cli(["audit", str(lp), "--no-advisories", "--format", "sarif"])
        doc = json.loads(out)
        self.assertEqual(doc["version"], "2.1.0")


# --------------------------------------------------------------------------- #
# pack: annotate / enrich / schema-version / pip
# --------------------------------------------------------------------------- #
class PackV041Tests(unittest.TestCase):
    def test_parse_annotations(self):
        ann = parse_annotations(["author=me", "tags=a,b,c", "target_vram_gb=24"])
        self.assertEqual(ann["author"], "me")
        self.assertEqual(ann["tags"], ["a", "b", "c"])
        self.assertEqual(ann["target_vram_gb"], 24)
        with self.assertRaises(RuntimeError):
            parse_annotations(["noequals"])

    def test_build_lock_records_environment(self):
        wf = {"nodes": [{"widgets_values": ["x.safetensors"]}]}
        lock = build_lock(wf, "w.json", None)
        self.assertIn("python", lock.environment)
        self.assertIn("platform", lock.environment)

    def test_build_lock_v1_no_environment(self):
        wf = {"nodes": []}
        lock = build_lock(wf, "w.json", None, lock_version=1)
        self.assertEqual(lock.environment, {})

    def test_enrich_during_build(self):
        wf = {"nodes": []}
        m = Model("f.safetensors", url="hf://o/r/f.safetensors")
        lock = build_lock(wf, "w.json", None, enrich=["hf"])
        # no models from the empty workflow; enrich a standalone model instead
        enrich.enrich_model(m, ["hf"])
        self.assertEqual(m.hf_repo_id, "o/r")
        self.assertEqual(lock.models, [])

    def test_workflow_hash(self):
        with tempfile.TemporaryDirectory() as td:
            wf = Path(td) / "w.json"
            wf.write_text('{"nodes": []}', encoding="utf-8")
            h = workflow_hash(wf)
            self.assertTrue(h.startswith("sha256:"))
            self.assertEqual(len(h), len("sha256:") + 64)

    def test_pack_scans_pip_requirements(self):
        from comfylock.scan import scan_pip_requirements

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            node = root / "custom_nodes" / "MyNode"
            node.mkdir(parents=True)
            (node / "requirements.txt").write_text(
                "torch==2.1.0\n# a comment\n-r other.txt\nnumpy>=1.0  # inline\n",
                encoding="utf-8",
            )
            reqs = scan_pip_requirements(root)
            self.assertIn("torch==2.1.0", reqs)
            self.assertIn("numpy>=1.0", reqs)
            self.assertNotIn("-r other.txt", reqs)

    def test_cli_schema_version_1(self):
        with tempfile.TemporaryDirectory() as td:
            wf = Path(td) / "w.json"
            wf.write_text('{"nodes": []}', encoding="utf-8")
            out = Path(td) / "w.lock"
            with _chdir(td):
                rc, _ = _run_cli(["pack", str(wf), "-o", str(out), "--schema-version", "1"])
            self.assertEqual(rc, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], 1)
            self.assertNotIn("environment", data)


# --------------------------------------------------------------------------- #
# init writes comfylock.toml
# --------------------------------------------------------------------------- #
class InitConfigTests(unittest.TestCase):
    def test_write_config_round_trips(self):
        from comfylock.init import write_config

        with tempfile.TemporaryDirectory() as td:
            p = write_config(Path(td) / "comfylock.toml", comfyui_root="/x/ComfyUI")
            cfg = config.read_config_file(p)
            self.assertEqual(cfg["comfyui_root"], "/x/ComfyUI")
            self.assertEqual(cfg["schema_version"], 2)


if __name__ == "__main__":
    unittest.main()
