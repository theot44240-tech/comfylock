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

# Hash types we can compute locally (used to pick a verifiable hash from a lock).
COMPUTABLE = ["SHA256", "AutoV2", "CRC32", "BLAKE2B", "AutoV1"]
if _HAS_BLAKE3:
    COMPUTABLE.insert(1, "BLAKE3")


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
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

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
