"""Model file hashing with a size+mtime cache.

Supported hash types:
  * SHA256  - streaming, conservative default, byte-identity.
  * BLAKE3  - fast; only available if the ``blake3`` package is installed.
  * BLAKE2B - fast stdlib alternative when BLAKE3 is unavailable.
  * CRC32   - cheap integrity check (zlib), 8 hex chars.
  * AutoV2  - Civitai: first 10 hex chars of the full-file SHA256.
  * AutoV1  - AUTOMATIC1111 model hash: SHA256 of 64 KiB at offset 1 MiB,
              first 8 hex chars (best-effort for small files).
"""

from __future__ import annotations

import hashlib
import json
import zlib
from pathlib import Path

try:  # optional fast hash
    import blake3  # type: ignore

    _HAS_BLAKE3 = True
except Exception:  # pragma: no cover - depends on environment
    _HAS_BLAKE3 = False

_CHUNK = 1024 * 1024  # 1 MiB

# Hash types we can compute locally (used when packing/diffing a lock).
COMPUTABLE = ["SHA256", "AutoV2", "CRC32", "BLAKE2B", "AutoV1"]
if _HAS_BLAKE3:
    COMPUTABLE.insert(1, "BLAKE3")

# Cryptographically strong, full-file digests. Only these are accepted as
# integrity evidence when admitting a download (``unpack``) or asserting a model
# is untampered (``verify``). A weak/truncated hash chosen by an *untrusted* lock
# provides no real protection against an adversary who controls the bytes (a MITM
# on the download, or a swapped artifact): CRC32 is a 32-bit non-cryptographic
# checksum, AutoV2 is only a 40-bit prefix of SHA256, and AutoV1 hashes at most a
# 64 KiB window -- all cheaply forgeable. They remain in COMPUTABLE so they can
# still be recorded by ``pack`` and compared by ``diff``; they just cannot, on
# their own, certify integrity. Order = preferred-first.
STRONG = ["SHA256", "BLAKE2B"]
if _HAS_BLAKE3:
    STRONG.insert(1, "BLAKE3")


def has_blake3() -> bool:
    return _HAS_BLAKE3


def _sha256_full(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def compute(path: str | Path, hash_type: str) -> str:
    """Compute a single hash of ``path`` as lowercase hex (no caching)."""
    p = Path(path)
    t = hash_type.upper()
    if t == "SHA256":
        return _sha256_full(p)
    if t == "AUTOV2":
        return _sha256_full(p)[:10]
    if t == "AUTOV1":
        with open(p, "rb") as f:
            f.seek(0x100000)
            region = f.read(0x10000)
        if not region:
            # The file is smaller than the 1 MiB offset, so the legacy A1111
            # window is empty -- hashing it would make *every* small file (e.g. a
            # few-KB embedding) collapse to the same constant sha256(b"")[:8],
            # which both defeats tamper detection and makes any small download
            # "verify". Fall back to a full-file digest so the value depends on
            # the content. (A1111 only ever applied the window to large
            # checkpoints; small files were always best-effort, see module doc.)
            return _sha256_full(p)[:8]
        return hashlib.sha256(region).hexdigest()[:8]
    if t == "CRC32":
        crc = 0
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK), b""):
                crc = zlib.crc32(chunk, crc)
        return format(crc & 0xFFFFFFFF, "08x")
    if t == "BLAKE2B":
        h = hashlib.blake2b()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK), b""):
                h.update(chunk)
        return h.hexdigest()
    if t == "BLAKE3":
        if not _HAS_BLAKE3:
            raise RuntimeError("BLAKE3 requested but the `blake3` package is not installed.")
        hb3 = blake3.blake3()  # type: ignore[attr-defined]
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK), b""):
                hb3.update(chunk)
        return hb3.hexdigest()  # type: ignore[no-any-return]
    raise ValueError(f"Unknown hash type: {hash_type!r}")


class HashCache:
    """Cache hashes keyed by (abs path, size, mtime_ns, type).

    A stale entry (file changed) is recomputed automatically. The cache is a
    plain JSON file so it is easy to inspect and safe to delete.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._data: dict[str, str] = {}
        if self.path and self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                loaded = {}
            # The cache file lives in the (shared/copied/corruptible) ComfyUI root
            # and is "safe to delete". A truncated or hand-edited file can be valid
            # JSON yet not an object (e.g. ``[1,2,3]``, ``42``, ``"x"``); json.loads
            # would then succeed and ``_data`` would be a non-dict, so the first
            # ``key in self._data`` / ``self._data[key] = ...`` raises an uncaught
            # TypeError. Fall back to an empty cache unless it is really a dict.
            self._data = loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _key(p: Path, hash_type: str) -> str:
        st = p.stat()
        return f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}|{hash_type.upper()}"

    def get(self, path: str | Path, hash_type: str) -> str:
        p = Path(path)
        key = self._key(p, hash_type)
        if key in self._data:
            return self._data[key]
        value = compute(p, hash_type)
        self._data[key] = value
        return value

    def save(self) -> None:
        if not self.path:
            return
        self.path.write_text(json.dumps(self._data, indent=0), encoding="utf-8")
