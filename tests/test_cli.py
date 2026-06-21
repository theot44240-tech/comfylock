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

    def test_unpack_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock = root / "wf.lock"
            lock.write_text(json.dumps({
                "version": 1,
                "models": [{"name": "m.safetensors",
                            "url": "https://example/m.safetensors",
                            "paths": [{"path": "models/checkpoints/m.safetensors"}]}],
            }))
            r = run(["unpack", str(lock), "-r", str(root)])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("dry run", r.stdout)


if __name__ == "__main__":
    unittest.main()
