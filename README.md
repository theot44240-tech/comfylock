<div align="center">

# 🔒 ComfyLock

### `pip freeze`, but for ComfyUI workflows.

**Pin your custom-node commits, model file hashes, and key parameters into one small,
portable, verifiable `.lock` file — so the workflow that works on your machine works on theirs.**

[![CI](https://github.com/theot44240-tech/comfylock/actions/workflows/ci.yml/badge.svg)](https://github.com/theot44240-tech/comfylock/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Zero dependencies](https://img.shields.io/badge/dependencies-0-success)](#-why-its-different)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-66%20unit%20%2B%2029%20selftest-brightgreen)](#-quality--proof-points)
[![Status: Beta](https://img.shields.io/badge/status-beta-yellow)](CHANGELOG.md)

[Quick start](#-quick-start-60-seconds) ·
[Why it's different](#-why-its-different) ·
[The lockfile](#-the-lockfile) ·
[ComfyUI panel](#-comfyui-panel) ·
[FAQ](#-faq)

</div>

---

> [!NOTE]
> **The one-liner:** ComfyLock turns a fragile, "works on my machine" ComfyUI workflow into a
> reproducible one. One command writes a tiny lockfile next to your `.flow.json`; one command
> on the other side tells you *exactly* what's missing or mismatched — and can fetch it back.

<!-- PLACEHOLDER: demo GIF — `comfy-lock pack` → `verify` → `unpack` round-trip in a terminal. -->
<!-- Drop a recording at docs/demo.gif and uncomment:
<div align="center"><img src="docs/demo.gif" alt="ComfyLock pack → verify → unpack demo" width="760"></div>
-->

---

## 🧨 The problem

Shared ComfyUI workflows break on someone else's machine all the time. The *same* `.flow.json`
graph silently produces different results — or refuses to load — because of:

| Layer | What goes wrong |
| --- | --- |
| 🧩 **Custom nodes** | The graph references node types you don't have installed. |
| 🔁 **Node versions** | A node updated and quietly changed its behavior. |
| 🎛️ **Model files** | Same filename, different weights — a different hash entirely. |
| 🎚️ **Parameters** | Sampler, scheduler, seed, or steps drifted without anyone noticing. |

ComfyUI ships and updates *fast*, which makes all four worse. The result is hours lost chasing
"why does this look different than the screenshot?"

**ComfyLock fixes this by pinning all of it at once** — into a single lightweight, local, diffable artifact.

---

## ⚡ Quick start (60 seconds)

> **Heads up:** ComfyLock isn't on PyPI yet (a release is on the [roadmap](#-roadmap)).
> Install it straight from GitHub today:

```bash
pip install "git+https://github.com/theot44240-tech/comfylock.git"
```

**1. Pack** — turn a workflow + your ComfyUI install into a lockfile:

```bash
comfy-lock pack my_workflow.flow.json -r /path/to/ComfyUI --hash SHA256 --hash AutoV2
# -> Wrote my_workflow.lock
```

**2. Verify** — on any machine, check reality against the lock:

```bash
comfy-lock verify my_workflow.lock -r /path/to/ComfyUI
# ok Node ComfyUI-Impact-Pack: 9d2a1c3b4e matches.
# XX Model 'sd_xl_base_1.0.safetensors': expected SHA256=31e35c80fc.. but got a1b2c3d4e5.. (re-download?).
# 1 error(s), 0 warning(s), 6 check(s).
```

**3. Unpack** — restore the missing pieces (preview first, then apply):

```bash
comfy-lock unpack my_workflow.lock -r /path/to/ComfyUI            # dry run, shows the plan
comfy-lock unpack my_workflow.lock -r /path/to/ComfyUI --apply    # clone nodes + download models
```

That's the whole loop: **pack → share the `.lock` → verify → unpack.**

---

## ✨ Why it's different

ComfyLock is deliberately small and sharp. The entire core is **pure Python standard library —
zero runtime dependencies.** YAML and BLAKE3 are *optional* extras, never requirements.

<table>
<tr><td>

🧷 **Three-layer pinning**
ComfyUI core commit · custom-node commits (git repos *and* local `.py` file nodes) · model file hashes.

</td><td>

🔢 **Multiple hash types**
SHA256 (default), AutoV2 / AutoV1 (Civitai / A1111 compatible), CRC32, BLAKE2B, and optional BLAKE3.

</td></tr>
<tr><td>

🎛️ **Parameter echo**
Seed, steps, cfg, sampler, scheduler, denoise and more — recorded for human-readable diffs.

</td><td>

🔍 **Semantic diff**
See exactly what changed between two versions of a workflow — nodes, models, and parameters.

</td></tr>
<tr><td>

✅ **Verify & restore**
Check an environment against a lock, or fetch the missing pieces to recreate it — hashes checked on the way in.

</td><td>

⚙️ **Reproducible by design**
`pack` honors `SOURCE_DATE_EPOCH`; two packs of the same environment are byte-identical. Great for CI and diffing.

</td></tr>
<tr><td>

🚀 **Big-model friendly**
A size + mtime cache avoids rehashing multi-gigabyte models on every run.

</td><td>

🖱️ **ComfyUI panel**
A **🔒 Save Lockfile** button right inside the ComfyUI web UI.

</td></tr>
</table>

### How it compares

Existing tools each cover *part* of the gap. ComfyLock's niche is a single shareable, diffable
artifact that pins all three layers — and stays dependency-free.

| | Pins node commits | Pins model hashes | Shareable & diffable artifact | Lightweight / zero-dep |
| --- | :---: | :---: | :---: | :---: |
| **ComfyLock** | ✅ | ✅ | ✅ | ✅ |
| ComfyUI-Manager *(snapshot)* | ✅ | ❌ | ⚠️ snapshot, not model-aware | ➖ |
| Comfy-Pack | ✅ | ✅ | ❌ bundles whole env (heavy, archived) | ❌ |
| comfy-cli `comfy-lock.yaml` | ⚠️ install-time config | ❌ | ❌ not a portable artifact | ➖ |

<sub>Comparison reflects each tool's documented scope, not a head-to-head benchmark.</sub>

---

## 🛠️ CLI reference

```text
comfy-lock pack    <workflow.json>  [-o out.lock] [-r COMFYUI_ROOT] [--hash TYPE]... [--no-cache]
comfy-lock verify  <workflow.lock>  [-r COMFYUI_ROOT] [--no-hash] [--no-cache]
comfy-lock unpack  <workflow.lock>   -r COMFYUI_ROOT  [--apply] [--no-models]
comfy-lock diff    <old.lock> <new.lock> [--exit-code]
comfy-lock selftest
```

| Command | What it does |
| --- | --- |
| `pack` | Read a workflow, scan the ComfyUI install, write a `.lock` with node commits, model hashes, and parameters. |
| `verify` | Compare the current environment to a lock. **Exit code is non-zero on any mismatch** — drop it straight into CI. |
| `unpack` | Dry-run by default; with `--apply`, clone/checkout custom nodes and download missing models, verifying hashes after each download. |
| `diff` | Semantic comparison of two locks. `--exit-code` returns 1 when they differ, like `git diff --exit-code`. |
| `selftest` | Run the built-in, offline self-test suite. |

<details>
<summary><b>More usage examples</b></summary>

See exactly what changed between two versions of a workflow:

```bash
comfy-lock diff v1.lock v2.lock
# - ComfyUI: 0b3e9f1a2c -> 7c4d5e6f70
# - Node https://github.com/ltdrdata/ComfyUI-Impact-Pack.git: 9d2a1c3b4e -> a1b2c3d4e5
# - Model sd_xl_base_1.0.safetensors hash: SHA256:31e35c80fc -> SHA256:a1b2c3d4e5
# - Parameter steps: 25 -> 40
```

Gate a CI job on a workflow staying reproducible:

```bash
comfy-lock pack my_workflow.flow.json -r ./ComfyUI -o /tmp/fresh.lock
comfy-lock diff committed.lock /tmp/fresh.lock --exit-code   # fails the job if anything drifted
```

Fast verify that skips multi-gig model hashing:

```bash
comfy-lock verify my_workflow.lock -r /path/to/ComfyUI --no-hash
```

</details>

---

## 🔄 How it works

```text
        YOUR MACHINE                          THE LOCKFILE                      THEIR MACHINE
 ┌───────────────────────┐            ┌────────────────────────┐         ┌───────────────────────┐
 │  workflow.flow.json    │           │  comfyui   <commit>     │         │  comfy-lock verify     │
 │  +                     │  pack ──▶  │  custom_nodes <commits> │  ──▶    │   → what's missing /   │
 │  ComfyUI install       │           │  models     <hashes>    │         │     mismatched?        │
 │  (nodes + models)      │           │  parameters <echo>      │         │  comfy-lock unpack     │
 └───────────────────────┘            └────────────────────────┘         │   → fetch & restore    │
        scan + hash                    small · canonical · diffable        └───────────────────────┘
```

`pack` scans the install and records identity (commits + hashes). The `.lock` travels with your
workflow (commit it to git). On the far side, `verify` reports drift and `unpack` closes the gap —
**hash-checking every download** so you get back the exact bytes that were pinned.

---

## 📄 The lockfile

A ComfyLock file is a small, deterministic record (canonical JSON; YAML supported) that links a
workflow to everything needed to reproduce it. It **does not bundle large models** — only
references, hashes, and URLs.

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

<details>
<summary><b>Field reference</b></summary>

- **`version`** — lock schema version, for forward compatibility.
- **`workflow`** — the workflow file this lock pins.
- **`comfyui`** — required ComfyUI core commit.
- **`custom_nodes.git`** — map of repo URL → required commit.
- **`custom_nodes.files`** — local `.py` file nodes (with an enabled/disabled flag).
- **`models[]`** — `name`, original `url`, on-disk `paths`, one or more `hashes` (`{type, hash}`),
  optional `type` and `size`.
- **`parameters`** — echoed key settings for human-readable diffs.

</details>

A complete, real example lives in [`examples/workflow.lock`](examples/workflow.lock).

---

## 🖱️ ComfyUI panel

The [`panel/`](panel/) folder is a ComfyUI custom node that adds a **🔒 Save Lockfile** button to
the ComfyUI web UI.

1. Copy or symlink `panel/` into `ComfyUI/custom_nodes/comfylock/`.
2. `pip install` ComfyLock into the same Python environment ComfyUI uses.
3. Restart ComfyUI. The button serializes the current graph, POSTs it to the
   `POST /comfylock/pack` route, and downloads a `workflow.lock`.

<!-- PLACEHOLDER: screenshot of the "🔒 Save Lockfile" button in the ComfyUI menu. -->
<!-- Drop an image at docs/panel.png and uncomment:
<div align="center"><img src="docs/panel.png" alt="Save Lockfile button in ComfyUI" width="420"></div>
-->

The panel's imports are guarded, so importing it outside a running ComfyUI is a no-op — safe for
linting and tests.

---

## 📦 Installation

```bash
# Recommended today (not yet on PyPI):
pip install "git+https://github.com/theot44240-tech/comfylock.git"
```

**Optional extras:**

```bash
# YAML lockfiles
pip install "comfylock[yaml] @ git+https://github.com/theot44240-tech/comfylock.git"
# Fast BLAKE3 hashing for large models
pip install "comfylock[blake3] @ git+https://github.com/theot44240-tech/comfylock.git"
```

**From source (for development):**

```bash
git clone https://github.com/theot44240-tech/comfylock.git
cd comfylock
pip install -e ".[dev]"
```

> A PyPI release enabling plain `pip install comfylock` is planned — see the [roadmap](#-roadmap).

---

## 📊 Quality & proof points

ComfyLock is small, but it's tested like it isn't.

| Metric | Value |
| --- | --- |
| 🧪 Unit tests | **66** (`pytest`) |
| 🔬 Built-in self-test checks | **29** (`comfy-lock selftest`, fully offline) |
| 🖥️ CI matrix | **Linux · macOS · Windows** × Python **3.9 / 3.11 / 3.12** |
| 🧹 Static analysis | `ruff` + `mypy` (typed, ships `py.typed`) |
| 📦 Runtime dependencies | **0** (pure standard library) |

Every release also round-trips the example lockfile in CI and self-tests the *built* package, not
just the source tree.

---

## ❓ FAQ

<details>
<summary><b>Does the lockfile contain my models?</b></summary>

No. It records *references* — URLs, hashes, sizes, and on-disk paths — never the multi-gigabyte
weights. Lockfiles stay tiny and safe to commit to git.
</details>

<details>
<summary><b>What does a matching hash actually guarantee?</b></summary>

**Byte-identity, not safety.** A matching hash means the file is exactly the one that was pinned —
not that the file is inherently trustworthy. Always source models and nodes from places you trust.
</details>

<details>
<summary><b>Is it safe to run <code>unpack --apply</code> on a lockfile someone sent me?</b></summary>

Treat lockfiles like any shared script. `unpack --apply` downloads files and runs `git clone` /
`checkout` against the listed repos, so only apply locks you trust and review them first. ComfyLock
confines every write to the ComfyUI root you pass with `-r`, refuses paths that escape it, and
hash-checks every download — but the URLs and repos themselves are only as trustworthy as their source.
See [Security](#-security).
</details>

<details>
<summary><b>Do I need YAML or BLAKE3?</b></summary>

No. The default format is dependency-free canonical JSON, and the default hash is stdlib SHA256.
YAML and BLAKE3 are opt-in extras for people who want them.
</details>

<details>
<summary><b>Why is verify slow the first time?</b></summary>

Hashing large model files takes time. ComfyLock caches results by size + mtime, so subsequent runs
are fast. Use `verify --no-hash` to skip model hashing entirely when you only care about nodes.
</details>

---

## 🗺️ Roadmap

- [ ] PyPI release (plain `pip install comfylock`).
- [ ] Resolve unknown nodes through the ComfyUI registry automatically.
- [ ] HuggingFace / Civitai aware downloads (auth, resume, mirrors).
- [ ] `pack --strict` to fail when any referenced model can't be located.
- [ ] ComfyUI-Manager snapshot import/export for interoperability.
- [ ] Optional embedded thumbnail / preview of the workflow in the lock.

---

## 🔐 Security

- `unpack` downloads files from URLs recorded in the lock and **runs git clone / checkout** against
  the listed repositories. Only run `unpack --apply` on locks from sources you trust, and review a
  lock before applying it.
- `unpack` **confines every write to the ComfyUI root** you pass with `-r`. Entries whose path
  escapes the root (via `..` or an absolute path) are refused with an `unsafe path` error and skipped.
- Every downloaded model is **hash-checked** against the lock; a mismatch is reported as an error
  and the bad file is removed.
- ComfyLock **never executes** workflow or custom-node code; it only reads files, computes hashes,
  and runs the git/network fetches you explicitly request.
- Hashes verify **byte-identity, not safety.** A matching hash means the file is the one that was
  pinned — not that it is trustworthy.

Found a vulnerability? Please open a [security advisory](https://github.com/theot44240-tech/comfylock/security/advisories/new)
or a private issue rather than a public report.

---

## 🤝 Contributing

Contributions are welcome! The bar is simple: **keep the core dependency-free** (standard library
only — optional features belong behind extras), add tests for new behavior, and update `CHANGELOG.md`.

```bash
pip install -e ".[dev]"
python -m unittest discover -s tests -v   # or: pytest
python -m comfylock selftest
ruff check comfylock tests panel
mypy comfylock
```

---

## 📜 License

Licensed under **Apache-2.0**. See [LICENSE](LICENSE).

<div align="center">

---

**If ComfyLock saves you a "why does this look different on my machine?" afternoon, consider giving it a ⭐.**

*Built for everyone who has ever shipped a ComfyUI workflow and hoped it would just work on the other side.*

</div>
