# Recording the terminal demo

The README's terminal demo can be refreshed as an animated GIF so it always
reflects the current CLI. This is a manual step (it needs a real terminal).

## Tools

- [asciinema](https://asciinema.org/) to record the session
- [agg](https://github.com/asciinema/agg) to convert the cast to a GIF

```bash
pip install asciinema
cargo install --git https://github.com/asciinema/agg   # or a prebuilt binary
```

## Record

```bash
asciinema rec demo.cast --cols 100 --rows 30
```

Then run the canonical loop against a sample ComfyUI install:

```bash
comfy-lock pack my_workflow.flow.json -r ~/ComfyUI
comfy-lock inspect my_workflow.lock
comfy-lock verify my_workflow.lock -r ~/ComfyUI
comfy-lock diff old.lock my_workflow.lock
```

Press `Ctrl-D` to stop recording.

## Convert and commit

```bash
agg demo.cast assets/demo.gif --font-size 16
git add assets/demo.gif
git commit -m "docs: refresh terminal demo"
```

Keep the GIF under ~2 MB (trim the cast, lower the font size, or shorten the
loop). Reference it from the README hero section.
