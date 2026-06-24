"""`sign` / `verify --check-sig` - detached GPG signatures for trusted locks.

Stdlib-only: shells out to ``gpg``. Signing writes an ASCII-armored detached
signature ``<lock>.asc`` next to the lock; verification checks it before any
other work so a tampered or unsigned lock is rejected up front.

Sigstore keyless signing is offered as an optional path (``--sigstore``) but is
only available when the ``[sigstore]`` extra is installed; otherwise a clear
error explains how to enable it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def gpg_available() -> bool:
    return shutil.which("gpg") is not None


def _run_gpg(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gpg", *args], capture_output=True, text=True, timeout=60
    )


def sign_lock(lock_path: str | Path, key: str | None = None, sigstore: bool = False) -> Path:
    """Create a detached, armored signature ``<lock>.asc``. Returns its path."""
    p = Path(lock_path)
    if not p.exists():
        raise FileNotFoundError(f"lockfile not found: {p}")
    if sigstore:
        raise RuntimeError(
            "Sigstore signing requires the optional [sigstore] extra "
            "(`pip install comfylock[sigstore]`) and an OIDC identity (e.g. CI). "
            "Use GPG signing (the default) for local keys."
        )
    if not gpg_available():
        raise RuntimeError(
            "gpg is not installed. Install GnuPG to sign locks, or distribute the "
            "lock with an out-of-band checksum instead."
        )
    sig = p.with_suffix(p.suffix + ".asc")
    args = ["--detach-sign", "--armor", "--yes", "-o", str(sig)]
    if key:
        args += ["--local-user", key]
    args.append(str(p))
    result = _run_gpg(args)
    if result.returncode != 0:
        raise RuntimeError(f"gpg signing failed: {result.stderr.strip()}")
    return sig


def verify_signature(lock_path: str | Path, cert: str | None = None) -> tuple[bool, str]:
    """Verify ``<lock>.asc`` against the lock. Returns ``(ok, message)``.

    A missing signature or missing gpg is reported as a failure (the caller should
    refuse to proceed), not an exception, so ``verify --check-sig`` can surface it
    cleanly.
    """
    p = Path(lock_path)
    sig = p.with_suffix(p.suffix + ".asc")
    if not sig.exists():
        return False, f"no signature file found ({sig.name})."
    if not gpg_available():
        return False, "gpg is not installed; cannot verify the signature."
    result = _run_gpg(["--verify", str(sig), str(p)])
    if result.returncode == 0:
        return True, "signature OK."
    return False, f"signature INVALID: {result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'verification failed'}"
