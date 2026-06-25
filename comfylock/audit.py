"""``audit`` -- scan pinned git custom nodes for published GitHub advisories.

Queries the public REST endpoint
``GET https://api.github.com/repos/{owner}/{repo}/security-advisories`` (no
authentication required for public repositories) and reports any advisory found,
with severity, CVE id and a link. Stdlib ``urllib`` only -- no third-party deps.

Non-GitHub nodes are skipped (and noted). Transient failures (rate limiting,
network errors, unreachable hosts) degrade to a warning so the scan never
crashes on a flaky network. Results are cached for one hour in a small JSON
sidecar so repeated CI runs do not hammer the API.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .model import Lockfile

GITHUB_API = "https://api.github.com"
CACHE_TTL = 3600  # seconds; one hour matches the prompt's "cache for 1 hour".


class RateLimited(RuntimeError):
    """Raised by a fetcher when GitHub answers 403/429 (rate limit / abuse)."""


@dataclass
class Advisory:
    ghsa_id: str
    severity: str
    summary: str
    cve_id: str | None = None
    url: str = ""

    @staticmethod
    def from_api(d: dict[str, Any]) -> Advisory:
        return Advisory(
            ghsa_id=str(d.get("ghsa_id", "") or ""),
            severity=str(d.get("severity", "") or "unknown").lower(),
            summary=str(d.get("summary", "") or "").strip(),
            cve_id=(str(d["cve_id"]) if d.get("cve_id") else None),
            url=str(d.get("html_url", "") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ghsa_id": self.ghsa_id,
            "severity": self.severity,
            "summary": self.summary,
            "cve_id": self.cve_id,
            "url": self.url,
        }


@dataclass
class NodeAudit:
    url: str
    owner: str | None
    repo: str | None
    advisories: list[Advisory] = field(default_factory=list)
    skipped: str | None = None  # reason if not a GitHub repo
    error: str | None = None  # reason if the lookup failed

    @property
    def label(self) -> str:
        return f"{self.owner}/{self.repo}" if self.owner else self.url

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "owner": self.owner,
            "repo": self.repo,
            "advisories": [a.to_dict() for a in self.advisories],
            "skipped": self.skipped,
            "error": self.error,
        }


@dataclass
class AuditResult:
    nodes: list[NodeAudit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def advisory_count(self) -> int:
        return sum(len(n.advisories) for n in self.nodes)

    @property
    def has_advisories(self) -> bool:
        return self.advisory_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "warnings": list(self.warnings),
            "advisory_count": self.advisory_count,
        }

    def render(self) -> str:
        lines: list[str] = []
        for n in self.nodes:
            if n.skipped:
                lines.append(f" -  {n.url} (skipped: {n.skipped})")
            elif n.error:
                lines.append(f" ?  {n.label} (lookup failed: {n.error})")
            elif not n.advisories:
                lines.append(f"ok  {n.label}: no advisories")
            else:
                lines.append(f"XX  {n.label}: {len(n.advisories)} advisory(ies)")
                for a in n.advisories:
                    cve = f" {a.cve_id}" if a.cve_id else ""
                    lines.append(f"      [{a.severity}] {a.ghsa_id}{cve} {a.summary}")
                    if a.url:
                        lines.append(f"      {a.url}")
        for w in self.warnings:
            lines.append(f"!!  {w}")
        lines.append(
            f"\naudit: {self.advisory_count} advisory(ies) across "
            f"{len(self.nodes)} node(s)."
        )
        return "\n".join(lines)


def parse_github_repo(url: str) -> tuple[str, str] | None:
    """Extract ``(owner, repo)`` from a GitHub URL, or None if it is not GitHub.

    Handles ``https://github.com/o/r(.git)``, ``git@github.com:o/r.git`` and URLs
    carrying embedded credentials. Returns None for any non-github.com host so
    those nodes are skipped rather than queried.
    """
    u = url.strip()
    if u.startswith("git@github.com:"):
        path = u[len("git@github.com:"):]
    else:
        parsed = urllib.parse.urlparse(u)
        host = parsed.netloc.lower()
        if "@" in host:  # strip user:pass@
            host = host.split("@", 1)[1]
        if host.endswith(":443"):
            host = host[:-4]
        if host not in ("github.com", "www.github.com"):
            return None
        path = parsed.path
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _github_fetch(owner: str, repo: str, timeout: float = 15.0) -> list[dict[str, Any]]:
    """Default fetcher: GitHub Security Advisories REST API (public, unauthenticated)."""
    url = (
        f"{GITHUB_API}/repos/{owner}/{repo}/security-advisories"
        "?per_page=100&state=published"
    )
    req = urllib.request.Request(  # noqa: S310 - https GitHub API
        url,
        headers={
            "User-Agent": "comfylock",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise RateLimited(f"GitHub rate limit ({exc.code}) for {owner}/{repo}") from exc
        if exc.code == 404:
            return []  # advisories disabled / repo gone -> treat as "none"
        raise RuntimeError(f"GitHub API {exc.code} for {owner}/{repo}") from exc
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict)]


def _load_cache(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    ac = data.get("audit_cache", {})
    return ac if isinstance(ac, dict) else {}


def _save_cache(path: str | Path, cache: dict[str, Any]) -> None:
    p = Path(path)
    existing: dict[str, Any] = {}
    if p.exists():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, ValueError, UnicodeDecodeError):
            existing = {}
    existing["audit_cache"] = cache
    try:
        p.write_text(json.dumps(existing, indent=0), encoding="utf-8")
    except OSError:  # pragma: no cover - best-effort cache
        pass


def audit_lock(
    lock: Lockfile,
    *,
    fetch: Callable[[str, str], list[dict[str, Any]]] | None = None,
    cache_path: str | Path | None = None,
    now: float | None = None,
) -> AuditResult:
    """Audit every git-backed node in ``lock`` for GitHub advisories.

    ``fetch`` is injectable so tests can supply advisories without a network;
    when omitted it is resolved to ``_github_fetch`` at call time (so the module
    attribute stays monkeypatchable). ``cache_path`` (if given) caches raw
    advisory payloads for ``CACHE_TTL`` seconds. ``now`` overrides the clock.
    """
    if fetch is None:
        fetch = _github_fetch
    result = AuditResult()
    ts = time.time() if now is None else now
    cache = _load_cache(cache_path)
    dirty = False
    for url in sorted(lock.git_nodes):
        gh = parse_github_repo(url)
        if gh is None:
            result.nodes.append(
                NodeAudit(url=url, owner=None, repo=None,
                          skipped="not a GitHub repository")
            )
            continue
        owner, repo = gh
        key = f"{owner}/{repo}"
        cached = cache.get(key)
        if isinstance(cached, dict) and (ts - float(cached.get("ts", 0))) < CACHE_TTL:
            raw = cached.get("advisories", [])
            advisories = [Advisory.from_api(a) for a in raw if isinstance(a, dict)]
            result.nodes.append(NodeAudit(url=url, owner=owner, repo=repo,
                                          advisories=advisories))
            continue
        try:
            raw = fetch(owner, repo)
        except RateLimited as exc:
            result.warnings.append(str(exc))
            result.nodes.append(NodeAudit(url=url, owner=owner, repo=repo,
                                          error="rate limited"))
            continue
        except (urllib.error.URLError, RuntimeError, OSError, ValueError) as exc:
            result.warnings.append(f"{key}: {exc}")
            result.nodes.append(NodeAudit(url=url, owner=owner, repo=repo,
                                          error=str(exc)))
            continue
        advisories = [Advisory.from_api(a) for a in raw if isinstance(a, dict)]
        result.nodes.append(NodeAudit(url=url, owner=owner, repo=repo,
                                      advisories=advisories))
        cache[key] = {"ts": ts, "advisories": raw}
        dirty = True
    if dirty and cache_path:
        _save_cache(cache_path, cache)
    return result
