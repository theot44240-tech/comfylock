# Docker

`comfy-lock export --format dockerfile` turns a lock into a reproducible
Dockerfile that pins the ComfyUI core commit and clones every custom node at its
locked commit.

```bash
comfy-lock export my_workflow.lock --format dockerfile -o Dockerfile
docker build -t my-comfyui .
```

## What it emits

- `FROM comfyanonymous/comfyui:latest`
- `RUN git fetch --all && git checkout <locked commit>` for the core
- one `git clone … && git checkout <commit>` per custom node
- model downloads as **commented** `# RUN … wget …` stubs, each followed by a
  `sha256sum -c` check

Model downloads are commented out by default so the image stays small and the
build never pulls tens of gigabytes unexpectedly. Uncomment the models you need
inside the image, or mount a models volume at runtime:

```bash
docker run --rm -p 8188:8188 -v /host/models:/ComfyUI/models my-comfyui
```

The Dockerfile carries `LABEL comfylock.version` and the workflow name so you can
trace an image back to the lock that produced it.
