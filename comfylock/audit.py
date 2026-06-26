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

import ipaddress
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .hashes import STRONG
from .model import Lockfile, Model

GITHUB_API = "https://api.github.com"
CACHE_TTL = 3600  # seconds; one hour matches the prompt's "cache for 1 hour".

# SARIF / generic severity levels.
ERROR = "error"
WARNING = "warning"
NOTE = "note"

# TLDs that frequently host throwaway / typo-squat download links. A model URL on
# one of these is not necessarily malicious, but worth a reviewer's eye (note).
_SUSPICIOUS_TLDS = {"zip", "mov", "xyz", "top", "click", "country", "gq", "tk"}


@dataclass
class Finding:
    """One static-audit result (no network)."""

    rule_id: str
    level: str
    message: str
    where: str = ""  # the node/model the finding is about

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "level": self.level,
            "message": self.message,
            "where": self.where,
        }


def _host(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if "@" in host:
        host = host.split("@", 1)[1]
    return host.split(":", 1)[0]


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _unsafe_path(value: str) -> bool:
    """True if a lock-supplied path would be refused by ``unpack`` confinement."""
    norm = value.replace("\\", "/")
    if not norm:
        return False
    if Path(value).is_absolute() or re.match(r"^[A-Za-z]:", value):
        return True
    return ".." in [seg for seg in norm.split("/")]


def _audit_url(rule_prefix: str, where: str, url: str, out: list[Finding]) -> None:
    scheme = urllib.parse.urlparse(url).scheme.lower()
    host = _host(url)
    if scheme == "http":
        out.append(Finding(
            f"{rule_prefix}-http", WARNING,
            f"insecure http:// URL (use https): {url}", where,
        ))
    if host and _is_ip(host):
        out.append(Finding(
            f"{rule_prefix}-ip", WARNING,
            f"URL points to a raw IP address ({host}), not a named host: {url}",
            where,
        ))
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    if tld in _SUSPICIOUS_TLDS:
        out.append(Finding(
            f"{rule_prefix}-tld", NOTE,
            f"URL uses an unusual TLD (.{tld}); double-check its provenance: {url}",
            where,
        ))


def _audit_model(m: Model, out: list[Finding]) -> None:
    for url in m.urls():
        _audit_url("model-url", m.name, url, out)
    # hash strength: a download the lock pins only with a forgeable hash cannot be
    # cryptographically verified by ``unpack`` (it will refuse to fetch it).
    if m.hashes and not any(m.hash_of(ht) for ht in STRONG):
        kinds = ", ".join(sorted({h.type for h in m.hashes}))
        out.append(Finding(
            "hash-weak", WARNING,
            f"model is pinned only with weak hash(es) [{kinds}]; add SHA256 so "
            f"unpack can verify it: {m.name}", m.name,
        ))
    # path traversal: would be refused by unpack's confinement.
    for p in m.paths:
        if _unsafe_path(p):
            out.append(Finding(
                "path-traversal", ERROR,
                f"model path escapes the ComfyUI root and would be refused by "
                f"unpack: {p}", m.name,
            ))
    # size anomaly: a checkpoint is rarely < 1 MB.
    if m.size is not None and 0 < m.size < 1_000_000:
        out.append(Finding(
            "size-small", WARNING,
            f"recorded size is {m.size} bytes (< 1 MB) -- suspiciously small for "
            f"a model: {m.name}", m.name,
        ))


def static_audit(lock: Lockfile) -> list[Finding]:
    """Offline security checks over a lockfile (no network).

    Covers URL safety (http/IP/odd TLD), hash strength, path traversal, and size
    anomalies. Network checks (GitHub advisories) live in :func:`audit_lock`.
    """
    out: list[Finding] = []
    for url in sorted(lock.git_nodes):
        _audit_url("node-url", url, url, out)
        name = url.rstrip("/").replace("\\", "/").split("/")[-1]
        if _unsafe_path(name):
            out.append(Finding(
                "node-path", ERROR,
                f"custom-node URL maps to an unsafe directory name: {url}", url,
            ))
    for fn in lock.file_nodes:
        if _unsafe_path(fn.filename):
            out.append(Finding(
                "node-path", ERROR,
                f"file-node name escapes custom_nodes/ and would be refused: "
                f"{fn.filename}", fn.filename,
            ))
    for m in sorted(lock.models, key=lambda m: m.name.lower()):
        _audit_model(m, out)
    return out


def sarif_run(findings: list[Finding]) -> dict[str, Any]:
    """Build the single SARIF 2.1.0 ``run`` object for ``findings``."""
    rule_ids = sorted({f.rule_id for f in findings})
    rules = [
        {"id": rid, "name": rid, "shortDescription": {"text": rid}}
        for rid in rule_ids
    ]
    results = [
        {
            "ruleId": f.rule_id,
            "level": f.level,
            "message": {"text": f.message},
            "locations": (
                [{"logicalLocations": [{"fullyQualifiedName": f.where}]}]
                if f.where else []
            ),
        }
        for f in findings
    ]
    return {
        "tool": {
            "driver": {
                "name": "comfylock",
                "informationUri": "https://github.com/theot44240-tech/comfylock",
                "version": __version__,
                "rules": rules,
            }
        },
        "results": results,
    }


def to_sarif(findings: list[Finding]) -> str:
    """A SARIF 2.1.0 document for GitHub Code Scanning / VS Code."""
    doc = {
        "version": "2.1.0",
        "$schema": (
            "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/"
            "Schemas/sarif-schema-2.1.0.json"
        ),
        "runs": [sarif_run(findings)],
    }
    return json.dumps(doc, indent=2) + "\n"


def render_static(findings: list[Finding]) -> str:
    """Human-readable text for static findings."""
    if not findings:
        return "audit: no static issues found."
    glyph = {ERROR: "XX", WARNING: "!!", NOTE: " -"}
    lines = [f"{glyph.get(f.level, '  ')} [{f.rule_id}] {f.message}" for f in findings]
    n_err = sum(1 for f in findings if f.level == ERROR)
    n_warn = sum(1 for f in findings if f.level == WARNING)
    n_note = sum(1 for f in findings if f.level == NOTE)
    lines.append(f"\naudit: {n_err} error(s), {n_warn} warning(s), {n_note} note(s).")
    return "\n".join(lines)


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
