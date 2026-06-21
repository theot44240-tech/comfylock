# ComfyLock

**The reproducibility lockfile for ComfyUI workflows.** A "pip freeze for
ComfyUI" — it pins your custom-node commits, model file hashes, and key
parameters into one small, portable, verifiable `.lock` file you can commit
alongside your workflow JSON.

[![CI](https://github.com/theot44240-tech/comfylock/actions/workflows/ci.yml/badge.svg)](https://github.com/theot44240-tech/comfylock/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-Apache--2.0-green)

---

## The problem

Shared ComfyUI workflows often break on someone else's machine. The same
`.flow.json` graph can produce different results — or fail to load — because of:

- **Missing custom nodes** (the graph references node types you don't have).
- **Mismatched node versions** (a node updated and changed its behavior).
- **Different model files** (same filename, different weights/hash).
- **Drifted parameters** (sampler, scheduler, seed quietly changed).

ComfyUI ships and updates fast, which makes this worse. Existing tools each cover
part of the gap: ComfyUI-Manager snapshots *which* nodes are installed but not
model hashes; Comfy-Pack bundles an entire environment but is heavyweight and
archived; comfy-cli's `comfy-lock.yaml` is an install-time config, not a
shareable, diffable artifact.

**ComfyLock** fills the gap with one lightweight, local-only lockfile that pins
all three layers at once: the node graph, the exact node commits, the model
hashes — plus the parameters that matter for a diff.

## Core features

- **Three-layer pinning** — ComfyUI core commit, custom-node commits (git repos
  and local `.py` file nodes), and model file hashes.
- **Multiple hash types** — SHA256 (default, byte-identity), AutoV2/AutoV1
  (Civitai/A1111 compatible), CRC32, BLAKE2B, and BLAKE3 (optional). A
  size+mtime cache avoids rehashing multi-gigabyte models.
- **Parameter echo** — seed, steps, cfg, sampler, scheduler, denoise, and more
  recorded for human-readable diffs.
- **Semantic diff** — see exactly what changed between two workflow versions.
- **Verify & restore** — check an environment against a lock, or fetch the
  missing pieces to recreate it.
- **Zero dependencies** — pure Python standard library. YAML and BLAKE3 are
  optional extras, not requirements.
- **ComfyUI panel** — a "Save Lockfile" button inside the ComfyUI web UI.

## Installation

```bash
pip install comfylock
```

Optional extras:

```bash
pip install "comfylock[yaml]"    # read/write YAML lockfiles
pip install "comfylock[blake3]"  # fast BLAKE3 hashing for large models
```

From source:

```bash
git clone https://github.com/theot44240-tech/comfylock.git
cd comfylock
pip install -e .
```

## CLI commands

```text
comfy-lock pack    <workflow.json>  [-o out.lock] [-r COMFYUI_ROOT] [--hash TYPE]...
comfy-lock verify  <workflow.lock>  [-r COMFYUI_ROOT] [--no-hash]
comfy-lock unpack  <workflow.lock>   -r COMFYUI_ROOT  [--apply] [--no-models]
comfy-lock diff    <old.lock> <new.lock>
comfy-lock selftest
```

| Command  | What it does |
| -------- | ------------ |
| `pack`   | Read a workflow, scan the ComfyUI install, write a `.lock` with node commits, model hashes, and parameters. |
| `verify` | Compare the current environment to a lock. Exit code is non-zero on any mismatch. |
| `unpack` | Dry-run by default; with `--apply`, clone/checkout custom nodes and download missing models, verifying hashes after each download. |
| `diff`   | Semantic comparison of two locks (added/removed/changed models, nodes, parameters). |
| `selftest` | Run the built-in offline self-test suite. |

## Usage examples

Create a lockfile from a workflow, scanning a ComfyUI install:

```bash
comfy-lock pack my_workflow.flow.json -r /path/to/ComfyUI --hash SHA256 --hash AutoV2
# -> wrote my_workflow.lock
```

Verify another machine matches the lock:

```bash
comfy-lock verify my_workflow.lock -r /path/to/ComfyUI
# ok ComfyUI: commit 0b3e9f1a2c matches.
# ok Node ComfyUI-Impact-Pack: 9d2a1c3b4e matches.
# XX Model 'sd_xl_base_1.0.safetensors': expected SHA256=31e35c80fc.. but got a1b2c3d4e5.. (re-download?).
# 1 error(s), 0 warning(s), 6 check(s).
```

Restore the missing pieces (preview, then apply):

```bash
comfy-lock unpack my_workflow.lock -r /path/to/ComfyUI            # dry run
comfy-lock unpack my_workflow.lock -r /path/to/ComfyUI --apply    # do it
```

See what changed between two versions of a workflow:

```bash
comfy-lock diff v1.lock v2.lock
# - ComfyUI: 0b3e9f1a2c -> 7c4d5e6f70
# - Node https://github.com/ltdrdata/ComfyUI-Impact-Pack.git: 9d2a1c3b4e -> a1b2c3d4e5
# - Model sd_xl_base_1.0.safetensors hash: SHA256:31e35c80fc -> SHA256:a1b2c3d4e5
# - Parameter steps: 25 -> 40
```

## Lockfile concept

A ComfyLock file is a small, deterministic record (canonical JSON; YAML
supported) that links a workflow to everything needed to reproduce it. It does
**not** bundle large models — only references, hashes, and URLs.

```json
{
  "version": 1,
  "workflow": "my_workflow.flow.json",
  "generated": "2026-06-21T12:00:00Z",
  "comfyui": "0b3e9f1a2c4d6e8f0a1b2c3d4e5f60718293a4b5",
  "custom_nodes": {
    "git": {
      "https://github.com/ltdrdata/ComfyUI-Impact-Pack.git": "9d2a1c3b4e..."
    },
    "files": [{ "filename": "my_inline_node.py", "disabled": false }]
  },
  "models": [
    {
      "name": "sd_xl_base_1.0.safetensors",
      "url": "https://huggingface.co/.../sd_xl_base_1.0.safetensors",
      "paths": [{ "path": "models/checkpoints/sd_xl_base_1.0.safetensors" }],
      "hashes": [{ "type": "SHA256", "hash": "31e35c80fc..." }],
      "type": "diffuser",
      "size": 6938040682
    }
  ],
  "parameters": { "seed": 123456789, "steps": 25, "sampler_name": "dpmpp_2m" }
}
```

Field reference:

- **`version`** — lock schema version, for forward compatibility.
- **`workflow`** — the workflow file this lock pins.
- **`comfyui`** — required ComfyUI core commit.
- **`custom_nodes.git`** — map of repo URL → required commit.
- **`custom_nodes.files`** — local `.py` file nodes (with enabled/disabled flag).
- **`models[]`** — `name`, original `url`, on-disk `paths`, one or more
  `hashes` (`{type, hash}`), optional `type` and `size`.
- **`parameters`** — echoed key settings for human-readable diffs.

A full example lives in [`examples/workflow.lock`](examples/workflow.lock).

## ComfyUI panel integration

The [`panel/`](panel/) folder is a ComfyUI custom node that adds a
**🔒 Save Lockfile** button to the ComfyUI web UI.

1. Copy or symlink `panel/` into `ComfyUI/custom_nodes/comfylock/`.
2. `pip install comfylock` into the same Python environment ComfyUI uses.
3. Restart ComfyUI. The button serializes the current graph, POSTs it to the
   `POST /comfylock/pack` route, and downloads a `workflow.lock`.

The panel imports are guarded, so importing it outside a running ComfyUI is a
no-op (safe for linting and tests).

## Roadmap

- Resolve unknown nodes through the ComfyUI registry automatically.
- HuggingFace / Civitai aware downloads (auth, resume, mirrors).
- `pack --strict` to fail when any referenced model can't be located.
- ComfyUI-Manager snapshot import/export for interoperability.
- Optional embedded thumbnail/preview of the workflow in the lock.

## Contributing

Contributions are welcome.

```bash
pip install -e ".[dev]"
python -m unittest discover -s tests -v
python -m comfylock selftest
ruff check comfylock tests panel
mypy comfylock
```

Please keep the core dependency-free (standard library only). Optional features
belong behind extras. Add tests for new behavior and update `CHANGELOG.md`.

## Security notes

- `unpack` downloads files from URLs recorded in the lock and **runs git clone /
  checkout** against the listed repositories. Only run `unpack --apply` on locks
  from sources you trust, and review a lock before applying it.
- Every downloaded model is hash-checked against the lock; a mismatch is
  reported as an error and the file is left in place for inspection.
- ComfyLock never executes workflow or custom-node code; it only reads files,
  computes hashes, and runs git/network fetches you explicitly request.
- Hashes verify **byte-identity**, not safety. A matching hash means the file is
  the one that was pinned, not that the file is trustworthy.

## License

Apache-2.0. See [LICENSE](LICENSE).
