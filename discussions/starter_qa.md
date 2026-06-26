# ❓ Q&A / Help

Stuck on something? Ask here. No question is too small.

To get a fast, useful answer, please include:

- **What you ran** — the full `comfy-lock …` command
- **What happened** — the output (wrap it in a ``` code block ```)
- **Your environment** — OS, Python version, and `comfy-lock --version`
- **Your lock**, if relevant (redact private URLs)

Common starting points:

- "Verify says a model is missing but it's right there" → check it's under
  `models/` and that the basename matches; run `comfy-lock doctor -r <root>`.
- "I want CI to fail when a node drifts" → `comfy-lock sync <lock> --check-only`.
- "Is `pip install comfylock` live yet?" → see the README install section.

Found an actual bug? Please open an [issue](https://github.com/theot44240-tech/comfylock/issues) instead.
