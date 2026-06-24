# ComfyUI-Manager interoperability

ComfyLock can round-trip with [ComfyUI-Manager](https://github.com/ltdrdata/ComfyUI-Manager)
snapshots, so you can share an environment with someone who uses CM's snapshot
system — and enrich a CM snapshot with model hashes that CM does not track.

## Export a CM snapshot from a lock

```bash
comfy-lock export my_workflow.lock --format manager-snapshot -o snapshot.json
```

The output matches CM's schema:

```json
{
  "comfyui": "<commit>",
  "git_custom_nodes": { "<url>": { "hash": "<commit>", "disabled": false } },
  "file_custom_nodes": [ { "filename": "x.py", "disabled": false } ],
  "pips": {}
}
```

## Import a CM snapshot into a lock

```bash
comfy-lock manager-import snapshot.json -o my_workflow.lock
```

CM snapshots pin the ComfyUI commit and custom nodes but **do not track models**,
so the imported lock has no model hashes (ComfyLock prints a warning). Re-pack the
same workflow with `-r <ComfyUI root>` afterwards to add model hashes and turn the
imported pins into a fully verifiable lock.

## Why bother?

CM snapshots reproduce *nodes*; ComfyLock additionally pins and verifies *model
file hashes and parameters*. The round-trip lets the two ecosystems share the
node half of an environment without either side reinventing the other.
