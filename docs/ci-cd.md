# CI / CD integration

Use `comfy-lock verify --exit-code`-style gating to keep an environment from
drifting. `verify` exits non-zero when the environment no longer matches the
lock; `diff --exit-code` exits 1 when two locks differ.

## GitHub Actions

```yaml
name: comfylock
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install comfylock
      - name: Verify the lock has not drifted
        run: comfy-lock diff committed.lock current.lock --exit-code
```

## GitLab CI

```yaml
verify:
  image: python:3.12
  script:
    - pip install comfylock
    - comfy-lock diff committed.lock current.lock --exit-code
```

## CircleCI

```yaml
version: 2.1
jobs:
  verify:
    docker:
      - image: cimg/python:3.12
    steps:
      - checkout
      - run: pip install comfylock
      - run: comfy-lock diff committed.lock current.lock --exit-code
```

## Pre-commit

Catch drift before it lands — see [pre-commit.md](pre-commit.md).

## Strict mode

Add `--strict` to make `pack` fail when a referenced model is missing, and to
turn `verify` warnings (ambiguous basenames, schema mismatch, weak-only hashes)
into failures:

```bash
comfy-lock pack wf.flow.json -r ~/ComfyUI --strict
comfy-lock verify wf.lock -r ~/ComfyUI --strict
```
