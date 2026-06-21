# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Nothing yet.

## [0.2.0] - 2026-06-21

### Added

- Reproducible lockfiles: `pack` honours `SOURCE_DATE_EPOCH`, so two packs of the
  same environment produce byte-identical output (handy for CI and diffing).
- `comfy-lock diff --exit-code` returns exit status 1 when lockfiles differ, for
  CI gating (mirrors `git diff --exit-code`).
- `verify` warns when a lockfile's schema version is newer than the installed
  tool, and when a model basename matches several files on disk (ambiguous).
- `unpack` routes downloaded models to the correct `models/<type>` subdirectory
  (loras, vae, controlnet, ...) based on the model `type` recorded in the lock,
  instead of always using `models/checkpoints`.

### Changed

- Model location is now deterministic: when several files share a basename the
  lexicographically smallest path is chosen, so repeated packs are stable.
- `pack` validates requested `--hash` types and fails clearly on unknown or
  unavailable algorithms (e.g. BLAKE3 without the optional package) instead of
  silently substituting SHA256.

### Fixed

- Malformed JSON/YAML lockfiles and workflows now produce a clear `error:`
  message with the file path and exit code 2, rather than an uncaught traceback.
- I/O and parse errors map to exit code 2; interrupts to 130.

## [0.1.0] - 2026-06-21

Initial release.

### Added

- `comfy-lock pack` - build a `.lock` file from a workflow plus the current
  ComfyUI environment (core commit, custom-node commits, model hashes, key
  parameters).
- `comfy-lock verify` - check the current environment against a lockfile and
  report missing nodes, wrong commits, and model hash/size mismatches.
- `comfy-lock unpack` - dry-run by default; with `--apply` it clones/checks out
  custom nodes and downloads missing models, verifying hashes after download.
- `comfy-lock diff` - semantic comparison of two lockfiles (models, nodes,
  parameters, schema version).
- `comfy-lock selftest` - offline, self-contained self-test suite.
- Model hashing: SHA256, AutoV2, AutoV1, CRC32, BLAKE2B, and BLAKE3 (optional),
  with a size+mtime hash cache to avoid rehashing large model files.
- JSON lockfile format (canonical, zero-dependency); YAML read/write supported
  when PyYAML is installed.
- ComfyUI panel extension (`panel/`) with a "Save Lockfile" button backed by a
  `POST /comfylock/pack` route.
- Apache-2.0 license, CI on Linux/macOS/Windows for Python 3.8/3.11/3.12, and a
  tag-driven release workflow.

[Unreleased]: https://github.com/theot44240-tech/comfylock/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/theot44240-tech/comfylock/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/theot44240-tech/comfylock/releases/tag/v0.1.0
