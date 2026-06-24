"""End-to-end CLI tests via ``python -m comfylock``."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kw):
    return subprocess.run(
        [sys.executable, "-m", "comfylock", *args],
        capture_output=True, text=True, cwd=str(ROOT), **kw,
    )


class CliTests(unittest.TestCase):
    def test_version(self):
        r = run(["--version"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("comfylock", r.stdout)

    def test_selftest_subcommand(self):
        r = run(["selftest"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("checks passed", r.stdout)

    def test_pack_verify_diff_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mdir = root / "models" / "checkpoints"
            mdir.mkdir(parents=True)
            (mdir / "m.safetensors").write_bytes(b"weights" * 200)
            wf = root / "wf.flow.json"
            wf.write_text(json.dumps(
                {"nodes": [{"widgets_values": ["m.safetensors"]}]}))
            lock = root / "wf.lock"

            r = run(["pack", str(wf), "-o", str(lock), "-r", str(root)])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(lock.exists())

            r = run(["verify", str(lock), "-r", str(root)])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

            # tamper -> verify fails (exit 1)
            (mdir / "m.safetensors").write_bytes(b"x")
            r = run(["verify", str(lock), "-r", str(root)])
            self.assertEqual(r.returncode, 1)

            # diff of a lock against itself: no differences
            r = run(["diff", str(lock), str(lock)])
            self.assertEqual(r.returncode, 0)
            self.assertIn("No differences", r.stdout)

    def test_diff_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "a.lock"
            b = root / "b.lock"
            a.write_text(json.dumps({"version": 1, "parameters": {"steps": 20}}))
            b.write_text(json.dumps({"version": 1, "parameters": {"steps": 50}}))
            # without flag: exit 0 even when different
            self.assertEqual(run(["diff", str(a), str(b)]).returncode, 0)
            # with flag: exit 1 when different
            self.assertEqual(run(["diff", str(a), str(b), "--exit-code"]).returncode, 1)
            # with flag: exit 0 when identical
            self.assertEqual(run(["diff", str(a), str(a), "--exit-code"]).returncode, 0)

    def test_pack_unknown_hash_clean_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wf = root / "wf.flow.json"
            wf.write_text(json.dumps({"nodes": []}))
            r = run(["pack", str(wf), "-o", str(root / "wf.lock"), "--hash", "MD5"])
            self.assertEqual(r.returncode, 2)
            self.assertIn("error:", r.stderr)
            self.assertNotIn("Traceback", r.stderr)

    def test_verify_malformed_lock_clean_error(self):
        with tempfile.TemporaryDirectory() as td:
            lock = Path(td) / "bad.lock"
            lock.write_text("{ not valid")
            r = run(["verify", str(lock)])
            self.assertEqual(r.returncode, 2)
            self.assertIn("error:", r.stderr)
            self.assertNotIn("Traceback", r.stderr)

    def test_missing_lock_clean_error(self):
        r = run(["verify", "nope-does-not-exist.lock"])
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)

    def test_verify_non_utf8_lock_clean_error(self):
        # A binary / mis-encoded lockfile raised UnicodeDecodeError (a ValueError),
        # which the CLI handler did not catch -> traceback. Now a clean exit 2.
        with tempfile.TemporaryDirectory() as td:
            lock = Path(td) / "bad.lock"
            lock.write_bytes(b'{"version":1,\xff\xfe"models":[]}')
            r = run(["verify", str(lock)])
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("error:", r.stderr)
            self.assertNotIn("Traceback", r.stderr)

    def test_verify_infinite_size_no_traceback(self):
        # JSON ``1e400`` -> float inf -> ``int(inf)`` OverflowError escaped as a
        # traceback. The field must coerce (to None) and verify must run cleanly.
        with tempfile.TemporaryDirectory() as td:
            lock = Path(td) / "inf.lock"
            lock.write_text(
                '{"version":1,"models":[{"name":"x.safetensors","size":1e400}]}')
            r = run(["verify", str(lock), "-r", td])
            self.assertNotIn("Traceback", r.stdout + r.stderr)
            self.assertIn(r.returncode, (0, 1))

    def test_unpack_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock = root / "wf.lock"
            lock.write_text(json.dumps({
                "version": 1,
                "models": [{"name": "m.safetensors",
                            "url": "https://example/m.safetensors",
                            "paths": [{"path": "models/checkpoints/m.safetensors"}],
                            "hashes": [{"type": "SHA256", "hash": "0" * 64}]}],
            }))
            r = run(["unpack", str(lock), "-r", str(root)])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("dry run", r.stdout)


if __name__ == "__main__":
    unittest.main()
