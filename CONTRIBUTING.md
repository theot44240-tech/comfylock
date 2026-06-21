# Contributing to ComfyLock

Thanks for your interest in improving ComfyLock. This project is a small,
dependency-free Python tool, so the contribution loop is fast.

## Development setup

ComfyLock targets Python 3.9+ and has **no runtime dependencies**. You only need
a recent Python and `git` on your `PATH`.

```bash
git clone https://github.com/theot44240-tech/comfylock
cd comfylock
python -m pip install -e ".[dev]"
```

The `[dev]` extra installs the tools used in CI: `pytest`, `ruff`, `mypy`, and
`pyyaml` (for the optional YAML lockfile format).

## Running the checks

CI runs exactly these. Run them locally before opening a pull request:

```bash
ruff check comfylock tests panel      # lint + import order
mypy comfylock                        # static types (package ships py.typed)
python -m unittest discover -s tests  # unit + integration tests
python -m comfylock selftest          # end-to-end self-test (needs git)
```

`pytest` works too if you prefer it (`pytest -q`); it discovers the same tests.

The self-test creates throwaway git repositories in a temp directory and
exercises a full `pack -> verify -> unpack -> diff` round-trip, so it is the
fastest way to confirm an end-to-end change still works.

## Coding guidelines

- **Standard library only.** Runtime code must not add third-party dependencies.
  Optional features (YAML, BLAKE3) are guarded behind soft imports and degrade
  gracefully when the extra is missing — keep it that way.
- **Type everything.** New public functions get type hints; `mypy` must stay
  clean.
- **Cross-platform.** ComfyLock is tested on Linux, macOS, and Windows. Avoid
  shell-isms; use `pathlib` and pass `subprocess` arguments as lists (never
  `shell=True`).
- **Determinism matters.** `pack` output must stay byte-stable for the same
  inputs (this is what makes lockfiles diffable). If you touch serialization,
  re-run the self-test and confirm two packs are identical.

## Adding a feature

1. Open an issue first for anything non-trivial so we can agree on scope.
2. Add or update a test in `tests/` and, where it makes sense, a check in
   `comfylock/selftest.py`.
3. Update `README.md` and `CHANGELOG.md` (under `[Unreleased]`).
4. Keep commits in [Conventional Commits](https://www.conventionalcommits.org)
   style (`feat:`, `fix:`, `docs:`, `ci:`, `refactor:`, `test:`).

## Reporting bugs

Open an issue using the bug template. A minimal `.flow.json` or `.lock` that
reproduces the problem, plus your OS and Python version, gets it fixed fastest.

## Code of conduct

Be kind, be constructive, and assume good faith. Harassment, discrimination, and
personal attacks aren't welcome here. Maintainers may remove comments, commits, or
contributors that violate this.
