"""``sync`` -- check pinned custom-node commits against their upstream remotes.

For each git-backed node the lock pins a commit. Over time the upstream default
branch moves on. ``sync`` runs ``git ls-remote`` (one cheap network round-trip per
repo, no clone) to compare the pinned commit with the remote ``HEAD``:

* ``up-to-date``        -- the pin *is* the current default-branch tip
* ``update-available``  -- the tip has moved; ``--update-nodes`` re-pins to it
* ``diverged``          -- the pinned commit is no longer any advertised ref
* ``unreachable``       -- ls-remote failed (offline, private, gone)

The remote query is injectable so tests run without a network. A lock is
untrusted input, so every URL is allow-listed (the same transport check
``unpack`` uses) before it is handed to ``git``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .model import Lockfile
from .scan import git
from .unpack import _safe_clone_url

# status constants
UP_TO_DATE = "up-to-date"
UPDATE_AVAILABLE = "update-available"
DIVERGED = "diverged"
UNREACHABLE = "unreachable"

LsRemote = Callable[[str], "dict[str, str]"]


def _git_ls_remote(url: str) -> dict[str, str]:
    """Return ``{ref: sha}`` advertised by ``url`` (empty on failure).

    Uses the hardened ``scan.git`` wrapper (ext::/fd:: transports disabled).
    """
    out = git(["ls-remote", "--", url], cwd=".")
    if not out:
        return {}
    refs: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0]:
            refs[parts[1].strip()] = parts[0].strip().lower()
    return refs


def _head_sha(refs: dict[str, str]) -> str | None:
    """The default-branch tip: prefer ``HEAD``, else main/master."""
    if "HEAD" in refs:
        return refs["HEAD"]
    for ref in ("refs/heads/main", "refs/heads/master"):
        if ref in refs:
            return refs[ref]
    return None


@dataclass
class NodeSync:
    url: str
    pinned: str
    status: str
    head: str | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "pinned": self.pinned,
            "status": self.status,
            "head": self.head,
            "detail": self.detail,
        }


@dataclass
class SyncResult:
    nodes: list[NodeSync] = field(default_factory=list)
    updated: int = 0

    @property
    def behind(self) -> int:
        return sum(1 for n in self.nodes if n.status in (UPDATE_AVAILABLE, DIVERGED))

    @property
    def unreachable(self) -> int:
        return sum(1 for n in self.nodes if n.status == UNREACHABLE)

    @property
    def all_current(self) -> bool:
        """True when nothing is behind (unreachable nodes do not fail the gate)."""
        return self.behind == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "updated": self.updated,
            "behind": self.behind,
            "unreachable": self.unreachable,
            "up_to_date": self.all_current,
        }

    def render(self) -> str:
        glyph = {
            UP_TO_DATE: "ok ",
            UPDATE_AVAILABLE: " ^ ",
            DIVERGED: " ! ",
            UNREACHABLE: " ? ",
        }
        lines = []
        for n in self.nodes:
            extra = f" ({n.detail})" if n.detail else ""
            lines.append(f"{glyph.get(n.status, '   ')} {n.url}: {n.status}{extra}")
        lines.append(
            f"\nsync: {self.behind} behind, {self.unreachable} unreachable, "
            f"{len(self.nodes)} node(s)."
        )
        if self.updated:
            lines.append(f"      {self.updated} pin(s) updated.")
        return "\n".join(lines)


def sync(
    lock: Lockfile,
    *,
    ls_remote: LsRemote | None = None,
    update_nodes: bool = False,
) -> tuple[Lockfile, SyncResult]:
    """Compare every git node's pin against its remote HEAD.

    Returns ``(new_lock, result)``. ``new_lock`` is a copy with pins re-pointed to
    the remote tip when ``update_nodes`` is set (otherwise identical to ``lock``).
    The input lock is never mutated in place.
    """
    fetch = ls_remote or _git_ls_remote
    result = SyncResult()
    new_nodes = dict(lock.git_nodes)
    for url in sorted(lock.git_nodes):
        pinned = lock.git_nodes[url].lower()
        if not _safe_clone_url(url):
            result.nodes.append(
                NodeSync(url, pinned, UNREACHABLE, detail="unsafe url (skipped)")
            )
            continue
        refs = fetch(url)
        head = _head_sha(refs)
        if not refs or head is None:
            result.nodes.append(NodeSync(url, pinned, UNREACHABLE, detail="ls-remote failed"))
            continue
        if pinned == head:
            result.nodes.append(NodeSync(url, pinned, UP_TO_DATE, head=head))
            continue
        # pin moved: is it still a known ref (behind) or gone (diverged)?
        advertised = set(refs.values())
        status = UPDATE_AVAILABLE if pinned in advertised else DIVERGED
        detail = f"HEAD={head[:10]}"
        result.nodes.append(NodeSync(url, pinned, status, head=head, detail=detail))
        if update_nodes:
            new_nodes[url] = head
            result.updated += 1

    new_lock = lock.copy()
    new_lock.git_nodes = new_nodes
    return new_lock, result
