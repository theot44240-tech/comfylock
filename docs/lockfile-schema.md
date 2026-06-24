# Lockfile schema

A ComfyLock lock is canonical, diffable JSON (YAML optional). The machine-readable
JSON Schema lives at [`schema/comfylock-v2.schema.json`](../schema/comfylock-v2.schema.json)
and is emitted by `comfy-lock export --format json-schema`.

Two schema versions exist; **v1 and v2 both read and write correctly**. `pack`
writes v2 by default; `pack --lock-version 1` writes v1.

## Top-level fields

| Field               | Versions | Description                                            |
| ------------------- | -------- | ------------------------------------------------------ |
| `version`           | 1, 2     | Schema version (integer).                              |
| `workflow`          | 1, 2     | Source workflow filename.                              |
| `generated`         | 1, 2     | UTC ISO-8601 timestamp (honours `SOURCE_DATE_EPOCH`).  |
| `comfylock_version` | 2        | Tool version that produced the lock.                   |
| `provenance`        | 2        | Opt-in author/machine metadata (hostname is hashed).   |
| `comfyui`           | 1, 2     | Pinned ComfyUI core commit.                            |
| `custom_nodes.git`  | 1, 2     | `{ repo_url: commit }`.                                |
| `custom_nodes.files`| 1, 2     | `[ { filename, disabled } ]`.                          |
| `models`            | 1, 2     | See below.                                             |
| `parameters`        | 1, 2     | Echoed key parameters (seed, steps, cfg, …).           |
| `thumbnail`         | 2        | Optional base64 PNG preview, or null.                  |

## Model fields

| Field                                   | Versions | Description                                  |
| --------------------------------------- | -------- | -------------------------------------------- |
| `name`                                  | 1, 2     | Model filename (basename).                   |
| `url`                                   | 1, 2     | Primary download URL.                        |
| `mirrors`                               | 2        | Fallback download URLs, tried in order.      |
| `paths`                                 | 1, 2     | `[ { path } ]` relative to the ComfyUI root. |
| `hashes`                                | 1, 2     | `[ { type, hash } ]` (SHA256, AutoV2, …).    |
| `type`                                  | 1, 2     | `checkpoint` / `lora` / `vae` / …            |
| `size`                                  | 1, 2     | Byte count.                                  |
| `civitai_model_id`, `civitai_version_id`| 2        | Civitai identifiers.                         |
| `hf_repo_id`, `hf_filename`             | 2        | HuggingFace Hub coordinates.                 |

All v2 fields are optional and backward-compatible: a v1 reader ignores them, and
`pack --lock-version 1` omits them entirely.

## Validate a lock

```bash
pip install jsonschema
python -c "import json,jsonschema; jsonschema.validate(json.load(open('my.lock')), json.load(open('schema/comfylock-v2.schema.json')))"
```
