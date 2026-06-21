# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Nothing yet.

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

[Unreleased]: https://github.com/theot44240-tech/comfylock/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/theot44240-tech/comfylock/releases/tag/v0.1.0
