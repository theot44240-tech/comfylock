# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `diff` now compares model hashes by their full digest, matched by hash type.
  Previously it compared only the first-listed hash's 10-character prefix, which
  had two consequences for `diff --exit-code` (a CI gate): a real content change
  whose new digest shared the old one's first 10 hex chars was reported as *no
  change* (a 40-bit prefix is brute-forceable, so a swapped model could slip past
  the gate), and the *same* model recorded with a different hash-type order
  (e.g. `AutoV2`-first vs `SHA256`-first, where `AutoV2` is literally the first
  10 hex of `SHA256`) was reported as a *phantom* change. Hashes are now matched
  by type and compared in full; when the prefixes of the displayed line collide
  it widens to the full digest. Covered by new tests and a `selftest` check.

### Security

- `unpack` now confines all writes to the target ComfyUI root. A lockfile is
  shared between machines and therefore untrusted; previously a crafted entry
  with a `path` containing `..` or an absolute path could make `unpack --apply`
  write a downloaded file (or clone a node) outside the root. Such entries are
  now refused with an `unsafe path` error and skipped; safe relative paths are
  unaffected. Covered by new tests and a `selftest` check.
- `verify` now confines a lockfile's custom-node URLs to the ComfyUI root before
  probing them. The directory checked for each git node is derived from the
  URL's last path segment, which is untrusted; on Windows that segment can be a
  UNC or rooted path (e.g. `\\attacker\share`) that escapes `custom_nodes`, so an
  unconfined existence check could leak NTLM credentials, hang on a remote share
  (DoS), or act as a file-existence oracle, and `..` could probe the root itself.
  Out-of-root URLs are now reported as a missing node instead of being stat'd.
  This completes the containment already applied to model paths and file nodes;
  `unpack` already guarded the same path. Covered by new tests and a `selftest`
  check.

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
