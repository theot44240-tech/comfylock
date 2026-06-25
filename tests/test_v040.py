"""Unit tests for the v0.4.0 surface (offline, no network).

audit / hash / doctor / export shell+requirements / the ``import`` alias /
``--json`` on verify and diff. Written as stdlib ``unittest`` so the CI
``unittest discover`` job (no pytest installed) runs them too.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from comfylock import cli, serialize
from comfylock.audit import Advisory, audit_lock, parse_github_repo
from comfylock.doctor import doctor
from comfylock.exporters import export
from comfylock.jsonout import Result, status_for
from comfylock.model import FileNode, Hash, Lockfile, Model


def _run_cli(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(argv)
    return rc, buf.getvalue()


def _vuln_fetch(owner, repo):
    if repo == "vuln":
        return [{
            "ghsa_id": "GHSA-aaaa-bbbb-cccc",
            "severity": "critical",
            "summary": "RCE in node loader",
            "cve_id": "CVE-2024-9999",
            "html_url": "https://github.com/acme/vuln/security/advisories/GHSA-x",
        }]
    return []


def _fake_comfy(root: Path) -> None:
    for sub in ("checkpoints", "loras", "vae", "controlnet", "clip", "unet"):
        (root / "models" / sub).mkdir(parents=True)
    (root / "custom_nodes").mkdir(parents=True)
    (root / "main.py").write_text("# comfy\n", encoding="utf-8")


class ParseGithubRepoTests(unittest.TestCase):
    CASES = [
        ("https://github.com/o/r.git", ("o", "r")),
        ("https://github.com/o/r", ("o", "r")),
        ("git@github.com:o/r.git", ("o", "r")),
        ("https://user:tok@github.com/o/r.git", ("o", "r")),
        ("https://github.com/o/r/tree/main", ("o", "r")),
        ("https://gitlab.com/o/r.git", None),
        ("https://example.com/o/r", None),
        ("https://github.com/onlyowner", None),
    ]

    def test_cases(self):
        for url, expected in self.CASES:
            with self.subTest(url=url):
                self.assertEqual(parse_github_repo(url), expected)


class AuditTests(unittest.TestCase):
    def test_reports_and_skips(self):
        lock = Lockfile(git_nodes={
            "https://github.com/acme/vuln.git": "a" * 40,
            "https://github.com/acme/clean.git": "b" * 40,
            "https://gitlab.com/x/y.git": "c" * 40,
        })
        res = audit_lock(lock, fetch=_vuln_fetch)
        self.assertTrue(res.has_advisories)
        self.assertEqual(res.advisory_count, 1)
        skipped = [n for n in res.nodes if n.skipped]
        self.assertEqual(len(skipped), 1)
        self.assertTrue(skipped[0].url.startswith("https://gitlab.com"))
        clean = [n for n in res.nodes if n.repo == "clean"]
        self.assertTrue(clean and not clean[0].advisories and not clean[0].error)
        self.assertIn("critical", res.render())

    def test_error_becomes_warning(self):
        def boom(owner, repo):
            raise RuntimeError("dns failure")

        lock = Lockfile(git_nodes={"https://github.com/a/b.git": "a" * 40})
        res = audit_lock(lock, fetch=boom)
        self.assertFalse(res.has_advisories)
        self.assertEqual(len(res.warnings), 1)
        self.assertTrue(res.nodes[0].error)

    def test_cache_hits_and_expires(self):
        calls = []

        def fetch(owner, repo):
            calls.append((owner, repo))
            return []

        lock = Lockfile(git_nodes={"https://github.com/a/b.git": "a" * 40})
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "audit-cache.json"
            audit_lock(lock, fetch=fetch, cache_path=cache, now=1000.0)
            self.assertTrue(cache.exists())
            audit_lock(lock, fetch=fetch, cache_path=cache, now=1000.0 + 60)
            self.assertEqual(len(calls), 1)  # within TTL -> cached
            audit_lock(lock, fetch=fetch, cache_path=cache, now=1000.0 + 4000)
            self.assertEqual(len(calls), 2)  # past TTL -> refetched

    def test_cli_fail_on_advisory_json(self):
        lock = Lockfile(git_nodes={"https://github.com/acme/vuln.git": "a" * 40})
        with tempfile.TemporaryDirectory() as td:
            lp = Path(td) / "w.lock"
            serialize.write(lock, lp)
            with mock.patch("comfylock.audit._github_fetch", new=_vuln_fetch):
                rc, out = _run_cli(
                    ["audit", str(lp), "--no-cache", "--fail-on-advisory", "--json"]
                )
        payload = json.loads(out)
        self.assertEqual(rc, 1)
        self.assertEqual(payload["command"], "audit")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["data"]["advisory_count"], 1)

    def test_advisory_from_api_tolerant(self):
        a = Advisory.from_api({})
        self.assertEqual(a.severity, "unknown")
        self.assertIsNone(a.cve_id)


class HashTests(unittest.TestCase):
    def test_cli_matches_stdlib(self):
        import hashlib

        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "model.bin"
            f.write_bytes(b"some-model-bytes" * 11)
            expected = hashlib.sha256(f.read_bytes()).hexdigest()
            rc, out = _run_cli(["hash", str(f), "--type", "SHA256", "--type", "CRC32"])
        self.assertEqual(rc, 0)
        self.assertIn(expected, out)
        self.assertIn("CRC32", out)

    def test_cli_json(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "model.bin"
            f.write_bytes(b"x" * 64)
            rc, out = _run_cli(["hash", str(f), "--json"])
        payload = json.loads(out)
        self.assertEqual(rc, 0)
        self.assertEqual(payload[0]["type"], "SHA256")
        self.assertEqual(len(payload[0]["hash"]), 64)


class DoctorTests(unittest.TestCase):
    def test_valid_install(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            _fake_comfy(root)
            self.assertEqual(doctor(comfyui_root=str(root)).n_errors, 0)

    def test_missing_root_errors(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertGreaterEqual(doctor(comfyui_root=str(Path(td) / "nope")).n_errors, 1)

    def test_not_a_comfy_dir(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "models").mkdir()
            (Path(td) / "custom_nodes").mkdir()
            self.assertGreaterEqual(doctor(comfyui_root=td).n_errors, 1)

    def test_lock_checks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            _fake_comfy(root)
            lp = Path(td) / "w.lock"
            serialize.write(Lockfile(models=[Model("a.safetensors")]), lp)
            rep = doctor(comfyui_root=str(root), lock_path=str(lp))
            msgs = " ".join(i.message for i in rep.issues)
            self.assertIn("no download URL", msgs)

    def test_cli_json(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            _fake_comfy(root)
            rc, out = _run_cli(["doctor", "-r", str(root), "--json"])
        payload = json.loads(out)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["command"], "doctor")
        self.assertTrue(payload["data"]["passed"])


class ExportShellRequirementsTests(unittest.TestCase):
    def test_shell(self):
        lock = Lockfile(
            comfyui="d" * 40,
            git_nodes={"https://github.com/a/b.git": "e" * 40},
            models=[Model(
                "m.safetensors", url="https://h/m",
                paths=["models/checkpoints/m.safetensors"],
                hashes=[Hash("SHA256", "f" * 64)],
            )],
        )
        sh = export(lock, "shell")
        self.assertTrue(sh.startswith("#!/usr/bin/env bash"))
        self.assertIn("git clone", sh)
        self.assertIn("sha256sum", sh)
        self.assertIn("f" * 64, sh)

    def test_shell_no_url_warns(self):
        sh = export(Lockfile(models=[Model("noidea.safetensors")]), "shell")
        self.assertIn("no download URL", sh)
        self.assertNotIn("sha256sum", sh)

    def test_requirements(self):
        lock = Lockfile(git_nodes={"https://github.com/a/b.git": "1" * 40})
        self.assertIn("git+https://github.com/a/b@" + "1" * 40, export(lock, "requirements"))

    def test_requirements_empty(self):
        self.assertIn("no git-backed custom nodes", export(Lockfile(), "requirements"))


class ImportAliasTests(unittest.TestCase):
    def test_import_alias(self):
        snap = {
            "comfyui": "abc123",
            "git_custom_nodes": {"https://github.com/a/b.git": {"hash": "9" * 40}},
            "file_custom_nodes": [{"filename": "x.py", "disabled": False}],
        }
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "snapshot.json"
            sp.write_text(json.dumps(snap), encoding="utf-8")
            out_lock = Path(td) / "from-import.lock"
            rc, _ = _run_cli(["import", str(sp), "-o", str(out_lock)])
            self.assertEqual(rc, 0)
            lock = serialize.read(out_lock)
        self.assertEqual(lock.comfyui, "abc123")
        self.assertIn("https://github.com/a/b.git", lock.git_nodes)


class JsonOutputTests(unittest.TestCase):
    def test_diff_json(self):
        with tempfile.TemporaryDirectory() as td:
            pa, pb = Path(td) / "a.lock", Path(td) / "b.lock"
            serialize.write(Lockfile(parameters={"steps": 20}), pa)
            serialize.write(Lockfile(parameters={"steps": 50}), pb)
            rc, out = _run_cli(["diff", str(pa), str(pb), "--json"])
        payload = json.loads(out)
        self.assertEqual(rc, 0)
        self.assertFalse(payload["data"]["empty"])
        self.assertTrue(any("steps" in c for c in payload["data"]["changes"]))

    def test_verify_json(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ComfyUI"
            (root / "models" / "checkpoints").mkdir(parents=True)
            (root / "custom_nodes").mkdir(parents=True)
            (root / "custom_nodes" / "present.py").write_text("# n\n", encoding="utf-8")
            lp = Path(td) / "w.lock"
            serialize.write(Lockfile(file_nodes=[FileNode("present.py")]), lp)
            _, out = _run_cli(["verify", str(lp), "-r", str(root), "--json"])
        payload = json.loads(out)
        self.assertEqual(payload["command"], "verify")
        self.assertIn("checks", payload["data"])
        self.assertIn(payload["status"], ("ok", "warning", "error"))

    def test_status_for(self):
        self.assertEqual(status_for([], []), "ok")
        self.assertEqual(status_for([], ["w"]), "warning")
        self.assertEqual(status_for(["e"], ["w"]), "error")

    def test_result_envelope(self):
        env = Result("x", "ok", {"k": 1}, [], []).envelope()
        self.assertEqual(env["command"], "x")
        self.assertEqual(env["status"], "ok")
        self.assertEqual(env["data"], {"k": 1})
        self.assertIn("version", env)


if __name__ == "__main__":
    unittest.main()
