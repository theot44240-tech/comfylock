# Security Policy

ComfyLock treats every lockfile as **untrusted input**. A `.lock` is shared
between machines (like a dependency freeze file), so it may have been authored or
modified by someone other than the person running `unpack`/`verify`. The threat
model and the guarantees below follow from that.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.3.x   | ✅        |
| 0.2.x   | ✅ (security fixes) |
| < 0.2   | ❌        |

## Reporting a vulnerability

Please report security issues **privately** via GitHub's
[private vulnerability reporting](https://github.com/theot44240-tech/comfylock/security/advisories/new)
rather than a public issue.

- Include a minimal reproducer (a `.lock` or `snapshot.json` and the exact
  command) where possible.
- We aim to acknowledge within **72 hours** and to ship a fix or mitigation for
  confirmed high-severity issues within **14 days**.

Please do not run exploits against infrastructure you do not own.

## What ComfyLock guarantees

- **Path containment.** `unpack` and `verify` confine every lock-supplied path
  (model `paths`, file-node names, the directory derived from a node URL) to the
  ComfyUI root. Absolute paths, `..` traversal, and Windows UNC/rooted segments
  are refused, never followed.
- **Transport allow-listing.** Custom-node URLs must be a standard transport
  (`https`/`http`/`git`/`ssh`/`file`, or `user@host:path`) with a hex commit
  before they reach `git`. `ext::`/`fd::` remote helpers (arbitrary code
  execution) and option-injection via a leading `-` are rejected, and `--` ends
  option parsing on every git call.
- **Strong-hash integrity gate.** A download is accepted only when it matches a
  strong full-file hash (SHA256, BLAKE3, or BLAKE2B) recorded in the lock. Weak
  or truncated hashes a lock might pin (CRC32, AutoV2, AutoV1) are recorded and
  diffed but never used on their own to certify a download. A hash mismatch
  deletes the partial bytes.
- **No surprise execution.** ComfyLock never executes model files or node code;
  it pins and verifies them. `unpack` performs network actions only with
  `--apply` (dry-run is the default).

## Safe use of `unpack --apply`

`unpack --apply` clones git repositories and downloads model files described by
the lock. Only run it against a lock you trust, ideally one you signed
(`comfy-lock sign`) or whose signature you verified
(`comfy-lock verify --check-sig`).
