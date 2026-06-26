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
        self.assertEqual(payload["data"]["advisories"]["advisory_count"], 1)

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


class ExportInjectionTests(unittest.TestCase):
    """A ``.lock`` is untrusted, shared input and the shell/dockerfile exports are
    *executed* (``bash install.sh`` / ``docker build``). Lock-controlled fields
    (commits, URLs, paths, hashes, workflow name) must never inject commands.
    """

    def test_shell_quotes_command_separator_injection(self):
        # comfyui core commit + node commit carrying a `;` command separator.
        lock = Lockfile(
            comfyui="aaaa; touch PWNED #",
            git_nodes={"https://github.com/a/b.git": "bbbb && touch PWNED"},
        )
        sh = export(lock, "shell")
        # The payloads survive only inside single quotes; the bare (executable)
        # forms must be absent.
        self.assertIn("git checkout 'aaaa; touch PWNED #'", sh)
        self.assertNotIn("git checkout aaaa; touch", sh)
        self.assertIn("git checkout 'bbbb && touch PWNED'", sh)
        self.assertNotIn("&& touch PWNED )", sh)

    def test_shell_blocks_substitution_and_quote_breakout_in_model_fields(self):
        import shlex as _shlex
        url = '"; rm -rf ~ ; echo "'             # double-quote breakout attempt
        dest = "models/x/$(touch PWNED).bin"     # command substitution attempt
        lock = Lockfile(models=[Model(
            "m.safetensors", url=url, paths=[dest],
            hashes=[Hash("SHA256", "f" * 64)],
        )])
        sh = export(lock, "shell")
        # Both fields appear only as a single shlex-quoted word; bash performs no
        # substitution inside single quotes and the `"` cannot break out.
        self.assertIn(f"dl {_shlex.quote(url)} {_shlex.quote(dest)}", sh)
        self.assertNotIn('dl "', sh)             # no double-quoted (injectable) args
        # Every generated line is well-formed shell (balanced quoting).
        for line in sh.splitlines():
            try:
                _shlex.split(line)
            except ValueError:
                self.fail(f"generated shell line does not parse: {line!r}")

    def test_dockerfile_blocks_newline_instruction_breakout(self):
        # A newline is the Dockerfile-specific vector: it ends the current line
        # and the next physical line is parsed as a fresh instruction.
        lock = Lockfile(
            workflow='wf"\nRUN touch PWNED\n#',
            comfyui="cccc\nRUN touch PWNED",
            git_nodes={"https://github.com/a/b.git": "dddd\nRUN touch PWNED"},
        )
        df = export(lock, "dockerfile")
        for line in df.splitlines():
            self.assertNotEqual(
                line.strip(), "RUN touch PWNED",
                "lock data broke out into a standalone RUN instruction",
            )
        # The workflow LABEL stays on exactly one physical line.
        labels = [ln for ln in df.splitlines()
                  if ln.startswith("LABEL comfylock.workflow")]
        self.assertEqual(len(labels), 1)

    def test_dockerfile_quotes_uncommentable_model_lines(self):
        # The template tells users to uncomment the model RUN lines, so they must
        # be shell-safe too even though they ship commented.
        import shlex as _shlex
        url = "$(touch PWNED)"
        dest = "models/x/m.safetensors"
        lock = Lockfile(models=[Model(
            "m.safetensors", url=url, paths=[dest],
            hashes=[Hash("SHA256", "f" * 64)],
        )])
        df = export(lock, "dockerfile")
        self.assertIn(f"wget -O {_shlex.quote(dest)} {_shlex.quote(url)}", df)
        self.assertNotIn(f"wget -O {dest} {url}", df)   # unquoted form absent

    def test_benign_values_stay_readable(self):
        # Quoting must not garble ordinary URLs/commits/paths (shlex leaves the
        # safe charset unquoted), so the common-case output is unchanged.
        lock = Lockfile(
            comfyui="d" * 40,
            git_nodes={"https://github.com/a/b.git": "e" * 40},
            models=[Model("m.safetensors", url="https://h/m.safetensors",
                          paths=["models/checkpoints/m.safetensors"],
                          hashes=[Hash("SHA256", "f" * 64)])],
        )
        sh = export(lock, "shell")
        self.assertIn("git checkout " + "d" * 40, sh)        # no quotes added
        self.assertIn("git clone https://github.com/a/b.git", sh)
        self.assertIn("dl https://h/m.safetensors models/checkpoints/m.safetensors", sh)


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
