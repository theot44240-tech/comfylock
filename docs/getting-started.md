# Getting started

ComfyLock pins a ComfyUI workflow's custom-node commits, model file hashes, and
key parameters into one small, portable `.lock` file — so you (or a teammate, or
a CI job, or future-you) can reproduce the exact environment.

## Install

```bash
pip install comfylock
# optional extras:
pip install "comfylock[yaml]"      # YAML lockfiles
pip install "comfylock[blake3]"    # fast BLAKE3 hashing
pip install "comfylock[hf]"        # HuggingFace Hub downloads (cached/gated)
```

ComfyLock's core has **zero runtime dependencies** — it runs in ComfyUI's own
portable Python and in stripped-down Docker images.

## First lock

```bash
# Pin a workflow against your ComfyUI install
comfy-lock pack my_workflow.flow.json -r ~/ComfyUI -o my_workflow.lock

# Or let the wizard walk you through it
comfy-lock init
```

On Windows the root looks like `-r C:\Users\you\ComfyUI` (or set
`COMFYUI_ROOT`). Paths inside the lock are stored with forward slashes and are
portable across operating systems.

## Inspect, verify, share

```bash
comfy-lock inspect my_workflow.lock          # human-readable summary
comfy-lock verify my_workflow.lock -r ~/ComfyUI
comfy-lock export my_workflow.lock --format markdown > SHARE.md
```

## Recreate elsewhere

```bash
comfy-lock unpack my_workflow.lock -r ~/ComfyUI            # dry run (preview)
comfy-lock unpack my_workflow.lock -r ~/ComfyUI --apply    # clone + download
```

`unpack` is a dry run by default; `--apply` actually clones nodes and downloads
models, verifying each against the lock's strong hash. See
[security.md](security.md) before applying a lock you did not author.

Next: [CI/CD integration](ci-cd.md) · [the lockfile schema](lockfile-schema.md).
