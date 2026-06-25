# Diagnosing issues (`comfy-lock doctor`)

`doctor` inspects a ComfyUI install and (optionally) a lockfile, and prints a
checklist where every failure comes with an actionable suggestion.

```bash
comfy-lock doctor -r ~/ComfyUI my_workflow.lock
```

Example output:

```
ok  ComfyUI entrypoint present in /home/me/ComfyUI
ok  models/ directory present
ok  custom_nodes/ directory present
ok  standard model subdirectories present
ok  git found on PATH
ok  found 1 lockfile(s): my_workflow.lock
ok  lock schema v2 is readable
!!  2/5 model(s) have no download URL: unpack cannot fetch them (add a url or place them manually)
ok  hash cache present and valid

0 error(s), 1 warning(s), 9 check(s).
```

## What it checks

- Whether `-r ROOT` looks like a real ComfyUI install (`main.py`/`server.py`,
  `models/`, `custom_nodes/`).
- The standard `models/` subdirectories (`checkpoints`, `loras`, `vae`,
  `controlnet`, `clip`, `unet`).
- Whether `git` is on `PATH` (needed for node pinning and `unpack`).
- `.lock` files in the current directory and the ComfyUI root.
- If a lockfile is given: schema version sanity, model count, and whether models
  carry download URLs.
- That the hash cache (`.comfylock-cache.json`) is present and valid.

## Exit code

`doctor` exits `1` if any **hard** check fails (missing root, missing
`models/`/`custom_nodes/`, no `git`), otherwise `0`. Warnings do not affect the
exit code. Add `--json` for a machine-readable result.
