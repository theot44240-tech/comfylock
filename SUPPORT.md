# Support

Thanks for using ComfyLock! Here is the fastest way to get help.

| I want to… | Go to |
|------------|-------|
| Ask a question / share a workflow | [GitHub Discussions](https://github.com/theot44240-tech/comfylock/discussions) |
| Report a bug | [Open an issue](https://github.com/theot44240-tech/comfylock/issues/new/choose) |
| Request a feature | [Open an issue](https://github.com/theot44240-tech/comfylock/issues/new/choose) |
| Report a security vulnerability | See [SECURITY.md](SECURITY.md) — please do **not** open a public issue |

## Before you open an issue

1. Run `comfy-lock doctor -r <ComfyUI root>` — it diagnoses the most common
   install/lockfile problems and suggests a fix for each.
2. Run `comfy-lock selftest` — if it fails, include the output; it points at the
   exact broken check.
3. Include your ComfyLock version (`comfy-lock --version`), Python version, and OS.

## Self-help

- `comfy-lock <command> --help` — full flags for any command.
- The [README](README.md) covers the whole `pack → verify → unpack` loop.
- The [docs/](docs/) directory has focused guides (CI/CD, Docker, signing,
  ComfyUI-Manager interop, the lockfile schema, and more).
