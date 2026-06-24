# Security & threat model

ComfyLock treats every lockfile as **untrusted input**: a `.lock` is shared
between machines like a dependency freeze file, so it may have been authored or
modified by someone other than the person running `unpack` / `verify`.

For the reporting process and supported versions, see the repository-level
[`SECURITY.md`](../SECURITY.md). This page is the practitioner's view.

## Guarantees

- **Path containment** — `unpack` and `verify` confine every lock-supplied path
  (model `paths`, file-node names, the directory derived from a node URL) to the
  ComfyUI root. Absolute paths, `..`, and Windows UNC/rooted segments are refused.
- **Transport allow-listing** — node URLs must be `https`/`http`/`git`/`ssh`/
  `file` (or `user@host:path`) with a hex commit before reaching `git`. The
  `ext::`/`fd::` remote helpers (arbitrary code execution) are disabled globally
  and `--` ends option parsing on every git call.
- **Strong-hash integrity gate** — a download is accepted only against a strong
  full-file hash (SHA256/BLAKE3/BLAKE2B). Weak hashes a lock might pin (CRC32,
  AutoV2, AutoV1) are recorded and diffed but never certify a download on their
  own. A hash mismatch deletes the partial bytes.
- **No execution** — ComfyLock pins and verifies files; it never runs model files
  or node code.

## Safe use of `unpack --apply`

`unpack --apply` performs network actions (clone, download). Run it only against a
lock you trust:

1. Prefer a **signed** lock — `comfy-lock verify <lock> --check-sig` rejects an
   unsigned or tampered lock before touching the filesystem (see
   [signed-locks.md](signed-locks.md)).
2. Review the **dry run** first (`unpack` without `--apply`) to see exactly what
   would be cloned and downloaded.
3. Keep model downloads pointed at sources you trust; the hash gate detects a
   swapped artifact, but a strong hash in an *untrusted* lock only proves the
   bytes match what the lock author chose.

## Reporting

Use GitHub's private vulnerability reporting — details in
[`SECURITY.md`](../SECURITY.md).
