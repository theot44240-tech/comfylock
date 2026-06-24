# Pre-commit hook

ComfyLock ships [`.pre-commit-hooks.yaml`](../.pre-commit-hooks.yaml) so you can
gate lock drift with [pre-commit](https://pre-commit.com/).

Add to your `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/theot44240-tech/comfylock
  rev: v0.3.0
  hooks:
    - id: comfylock-verify    # verify the environment matches each .lock (fast, --no-hash)
    - id: comfylock-diff      # fail if a committed .lock changed (diff --exit-code)
```

Then:

```bash
pip install pre-commit
pre-commit install
```

## Hooks

| id                | what it does                                              |
| ----------------- | -------------------------------------------------------- |
| `comfylock-verify`| Runs `comfy-lock verify --no-hash` on staged `*.lock`.   |
| `comfylock-diff`  | Runs `comfy-lock diff --exit-code` to assert no drift.   |

`comfylock-verify` uses `--no-hash` by default so the hook stays fast; drop that
arg in your config if you want full hash verification on every commit.
