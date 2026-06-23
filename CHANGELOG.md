# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `pack` no longer crashes on a malformed UI-graph workflow whose node `inputs`
  is a non-list scalar (e.g. `"inputs": 5`). The previous `... or []` kept the
  scalar and `for inp in 5` raised an uncaught `TypeError`, surfacing as a Python
  traceback instead of the CLI's clean error; such a node is now skipped.
- `pack` no longer crashes when `SOURCE_DATE_EPOCH` is a valid integer but out of
  the platform's representable range (e.g. a huge or very negative value). The
  `datetime.fromtimestamp` call raised an uncaught `OverflowError`/`OSError`; pack
  now falls back to the current time, like it already did for non-numeric values.
- The hash cache no longer crashes when its on-disk file (`.comfylock-cache.json`,
  which lives in the shared/copyable ComfyUI root) is valid JSON but not an object
  — e.g. a truncated write leaving `[1,2,3]`, a bare number, or a string. Parsing
  succeeded so the old code stored a non-`dict` and raised an uncaught `TypeError`
  on first lookup; it now falls back to an empty cache.
- `diff` no longer reports a phantom hash change when one lock records a model's
  `SHA256` and the other records only the derived `AutoV2` (the first 10 hex of
  that SHA256) — e.g. a re-pack with `--hash AutoV2`, or a Civitai-imported lock.
  The earlier "match by type" fix only reconciled overlapping hash types; the
  disjoint `SHA256`/`AutoV2` case slipped through and broke `diff --exit-code`. A
  genuinely unrelated `AutoV2` is still surfaced as a change.
- `verify` now checks a model at the path the lock recorded before falling back
  to a basename search. Previously it resolved every model by basename first
  (the lexicographically-smallest match under `models/`) and only consulted the
  lock's recorded `paths` when that search found nothing. When two files share a
  basename across `models/` subdirectories — common, e.g. the same LoRA copied
  into two folders — `verify` hashed the wrong file: a false hash/size-mismatch
  error on an otherwise-clean environment, and a way for a same-named decoy in an
  earlier-sorting subdir to mask the genuinely pinned artifact. The recorded path
  (confined to the root, as before) now wins when it still exists; the basename
  search remains the fallback so a model that legitimately moved subfolders still
  resolves. This matches how `unpack._model_present` already resolved presence.
  Covered by new tests and a `selftest` check.
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

- Integrity is now certified only by a strong full-file hash (SHA256, BLAKE3, or
  BLAKE2B). A lockfile is untrusted and supplies both a model's download URL and
  the hash used to check it, so a weak hash it pins gives no real protection
  against a tampered or swapped artifact: CRC32 is a 32-bit checksum, AutoV2 is a
  40-bit prefix of SHA256, and AutoV1 covers at most a 64 KiB window. `unpack` now
  refuses to fetch a model that pins only such a hash (`no strong hash to verify
  download`), and `verify` reports `integrity not cryptographically verified`
  instead of a confident match — the two commands now agree on what is
  verifiable. These types are still recorded by `pack` and compared by `diff`.
- `AutoV1` no longer collapses every sub-1 MiB file to a single constant. Its
  64 KiB window starts at offset 1 MiB, so for smaller files the window was empty
  and **all** of them hashed to `sha256(b"")[:8]` — making any small download or
  model "verify" against arbitrary content. Small files now fall back to a
  full-file digest so the value depends on the bytes.
- `unpack`/`verify` now derive a custom-node's directory name as a single clean
  path component. The name comes from the node URL's last segment; splitting only
  on `/` meant that on Windows a segment like `x\..\loras` carried backslash
  separators and `..` into the join, landing a clone in another subdirectory of
  the root (e.g. `models/`) instead of under `custom_nodes/`. The segment is now
  split on both separators and a bare `.`/`..` is rejected (`is_within` still
  guards the final path).
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
