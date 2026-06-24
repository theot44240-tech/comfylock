"""Model download engine: HuggingFace/Civitai aware, resumable, mirror-capable.

Zero required dependencies -- everything works with ``urllib``. ``huggingface_hub``
is used when present (the optional ``[hf]`` extra) for cached/gated HF downloads,
and falls back to plain HTTPS otherwise.

Design notes:
* ``detect_origin`` classifies a URL so the right auth/transform applies.
* ``prepare_url`` injects a Civitai token and rewrites ``hf://`` to an HTTPS
  ``resolve`` URL when the Hub library is unavailable.
* ``http_download`` resumes a partial file with an HTTP ``Range`` request and
  streams a textual progress bar to stderr.
* ``download`` tries the primary URL then each mirror in order.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

try:  # optional [hf] extra
    from huggingface_hub import hf_hub_download  # type: ignore

    _HAS_HF = True
except Exception:  # pragma: no cover - depends on environment
    _HAS_HF = False

ProgressCb = Callable[[int, int], None]


def has_hf() -> bool:
    return _HAS_HF


def detect_origin(url: str) -> str:
    """Classify a URL: ``huggingface`` | ``civitai`` | ``file`` | ``http``."""
    low = url.lower()
    if low.startswith("hf://"):
        return "huggingface"
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if host in ("huggingface.co", "hf.co") or host.endswith(".huggingface.co"):
        return "huggingface"
    if host == "civitai.com" or host.endswith(".civitai.com"):
        return "civitai"
    if parsed.scheme == "file":
        return "file"
    return "http"


def _civitai_with_token(url: str) -> str:
    key = os.environ.get("CIVITAI_API_KEY")
    if not key:
        return url
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    query.setdefault("token", key)
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def _hf_to_https(url: str) -> str:
    """Rewrite ``hf://org/repo/path/to/file`` to an HTTPS ``resolve`` URL."""
    rest = url[len("hf://"):]
    parts = rest.split("/")
    if len(parts) < 3:
        return url
    org, repo = parts[0], parts[1]
    path = "/".join(parts[2:])
    return f"https://huggingface.co/{org}/{repo}/resolve/main/{path}"


def prepare_url(url: str) -> str:
    """Apply origin-specific rewrites (Civitai token, hf:// -> https fallback)."""
    origin = detect_origin(url)
    if origin == "civitai":
        return _civitai_with_token(url)
    if origin == "huggingface" and url.lower().startswith("hf://"):
        return _hf_to_https(url)
    return url


def _hf_download(url: str, dest: Path) -> None:
    """Download an ``hf://org/repo/path`` URL via huggingface_hub (cached/gated)."""
    rest = url[len("hf://"):]
    parts = rest.split("/")
    if len(parts) < 3:
        raise RuntimeError(f"malformed hf:// URL: {url}")
    repo_id = f"{parts[0]}/{parts[1]}"
    filename = "/".join(parts[2:])
    token = os.environ.get("HF_TOKEN")
    cached = hf_hub_download(repo_id=repo_id, filename=filename, token=token)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = Path(cached).read_bytes()
    dest.write_bytes(data)


def _render_progress(done: int, total: int) -> None:
    if total <= 0:
        sys.stderr.write(f"\r  {done / 1_000_000:.1f} MB")
    else:
        pct = done * 100 // total
        sys.stderr.write(
            f"\r  {done / 1_000_000:.1f} / {total / 1_000_000:.1f} MB ({pct}%)"
        )
    sys.stderr.flush()


def http_download(
    url: str,
    dest: Path,
    resume: bool = True,
    progress: bool = True,
    chunk: int = 1024 * 256,
) -> None:
    """Download ``url`` to ``dest`` with optional resume and progress.

    Resume sends ``Range: bytes=<n>-`` when a partial file exists; a server that
    answers ``200`` (no range support) restarts cleanly from zero.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if url.lower().startswith("file:"):
        # No range/progress for local files: copy straight through.
        with urllib.request.urlopen(url) as r:  # noqa: S310 - file:// is intentional
            dest.write_bytes(r.read())
        return

    existing = dest.stat().st_size if (resume and dest.exists()) else 0
    headers = {"User-Agent": "comfylock"}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    req = urllib.request.Request(url, headers=headers)  # noqa: S310

    try:
        resp = urllib.request.urlopen(req)  # noqa: S310
    except urllib.error.HTTPError as exc:
        if exc.code == 416:  # requested range not satisfiable -> already complete
            return
        if exc.code == 401:
            raise RuntimeError(
                f"401 Unauthorized for {url} -- a token may be required "
                "(set HF_TOKEN or CIVITAI_API_KEY)."
            ) from exc
        raise

    status = getattr(resp, "status", 200) or 200
    append = status == 206 and existing > 0
    mode = "ab" if append else "wb"
    start = existing if append else 0
    length_header = resp.headers.get("Content-Length")
    total = (int(length_header) + start) if length_header and length_header.isdigit() else 0

    done = start
    with resp, open(dest, mode) as f:
        while True:
            block = resp.read(chunk)
            if not block:
                break
            f.write(block)
            done += len(block)
            if progress:
                _render_progress(done, total)
    if progress:
        sys.stderr.write("\n")
        sys.stderr.flush()


def download(
    urls: list[str],
    dest: Path,
    resume: bool = True,
    progress: bool = True,
) -> str:
    """Try each URL (primary then mirrors) until one downloads. Returns the URL used.

    Raises the last error if every URL fails.
    """
    if not urls:
        raise RuntimeError("no download URL")
    last_exc: Exception | None = None
    for raw in urls:
        try:
            if raw.lower().startswith("hf://") and _HAS_HF:
                _hf_download(raw, dest)
            else:
                http_download(prepare_url(raw), dest, resume=resume, progress=progress)
            return raw
        except Exception as exc:  # try the next mirror
            last_exc = exc
            continue
    raise RuntimeError(f"all download URLs failed: {last_exc}")
