"""Command-line interface for ComfyLock.

``comfy-lock <pack|verify|unpack|diff|inspect|export|manager-import|merge|gc|
update|sign|init|completions|selftest> ...``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, serialize
from .diff import diff as diff_locks
from .hashes import COMPUTABLE, HashCache
from .model import SCHEMA_VERSION
from .pack import pack as do_pack
from .unpack import unpack as do_unpack
from .verify import verify as do_verify

DEFAULT_CACHE = ".comfylock-cache.json"


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--comfyui-root",
        "-r",
        default=None,
        help="Path to the ComfyUI install (for node/model scanning).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="comfy-lock",
        description="Reproducibility lockfile for ComfyUI workflows.",
    )
    parser.add_argument(
        "--version", action="version", version=f"comfylock {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- pack ---
    p_pack = sub.add_parser("pack", help="Create a lockfile from a workflow.")
    p_pack.add_argument("workflow", help="Path to the workflow .json / .flow.json.")
    p_pack.add_argument("-o", "--out", default=None, help="Output lock path (default: <workflow>.lock).")
    p_pack.add_argument(
        "--hash", action="append", default=None, metavar="TYPE",
        help=f"Hash type(s) to record. Repeatable. One of: {', '.join(COMPUTABLE)}.",
    )
    p_pack.add_argument("--no-cache", action="store_true", help="Disable the hash cache.")
    p_pack.add_argument(
        "--lock-version", type=int, choices=(1, 2), default=SCHEMA_VERSION,
        help="Lockfile schema version to write (default: %(default)s).",
    )
    p_pack.add_argument(
        "--strict", action="store_true",
        help="Fail (exit 2) if any model referenced by the workflow is missing on disk.",
    )
    p_pack.add_argument(
        "--provenance", action="store_true",
        help="Record opt-in author/machine metadata (v2 only; not reproducible).",
    )
    _add_common(p_pack)

    # --- verify ---
    p_verify = sub.add_parser("verify", help="Check the environment against a lockfile.")
    p_verify.add_argument("lock", help="Path to the lockfile.")
    p_verify.add_argument("--no-hash", action="store_true", help="Skip model hashing (fast).")
    p_verify.add_argument("--no-cache", action="store_true", help="Disable the hash cache.")
    p_verify.add_argument(
        "--strict", action="store_true",
        help="Treat warnings (ambiguity, schema, weak hashes) as failures (exit 1).",
    )
    p_verify.add_argument(
        "--check-sig", action="store_true",
        help="Verify a detached GPG signature (<lock>.asc) before anything else.",
    )
    _add_common(p_verify)

    # --- unpack ---
    p_unpack = sub.add_parser("unpack", help="Fetch missing nodes/models from a lockfile.")
    p_unpack.add_argument("lock", help="Path to the lockfile.")
    p_unpack.add_argument("--apply", action="store_true", help="Actually perform actions (default is a dry run).")
    p_unpack.add_argument("--no-models", action="store_true", help="Do not download models.")
    p_unpack.add_argument(
        "--jobs", type=int, default=1, metavar="N",
        help="Download up to N models in parallel (default: 1).",
    )
    _add_common(p_unpack)

    # --- diff ---
    p_diff = sub.add_parser("diff", help="Show semantic changes between two lockfiles.")
    p_diff.add_argument("old", help="Old lockfile.")
    p_diff.add_argument("new", help="New lockfile.")
    p_diff.add_argument(
        "--exit-code", action="store_true",
        help="Exit 1 when the lockfiles differ (for CI gating, like `git diff`).",
    )

    # --- inspect ---
    p_inspect = sub.add_parser("inspect", help="Human-readable summary of a lockfile.")
    p_inspect.add_argument("lock", help="Path to the lockfile.")
    p_inspect.add_argument("--json", action="store_true", help="Re-emit canonical JSON (for jq).")
    p_inspect.add_argument("--no-color", action="store_true", help="Disable ANSI colour.")

    # --- export ---
    from .exporters import FORMATS

    p_export = sub.add_parser("export", help="Export a lock to another format.")
    p_export.add_argument("lock", help="Path to the lockfile.")
    p_export.add_argument("--format", required=True, choices=FORMATS, help="Export target.")
    p_export.add_argument("-o", "--out", default=None, help="Write to a file instead of stdout.")

    # --- manager-import ---
    p_mi = sub.add_parser("manager-import", help="Build a lock from a ComfyUI-Manager snapshot.")
    p_mi.add_argument("snapshot", help="Path to the ComfyUI-Manager snapshot.json.")
    p_mi.add_argument("-o", "--out", default=None, help="Output lock path (default: <snapshot>.lock).")
    _add_common(p_mi)

    # --- merge ---
    p_merge = sub.add_parser("merge", help="Merge several locks into one environment lock.")
    p_merge.add_argument("locks", nargs="+", help="Lockfiles to merge (2+).")
    p_merge.add_argument("-o", "--out", required=True, help="Output combined lock path.")
    p_merge.add_argument(
        "--strategy", choices=("first", "strict"), default="first",
        help="Conflict handling: keep first (default) or fail on any conflict.",
    )

    # --- gc ---
    p_gc = sub.add_parser("gc", help="Find model files not referenced by any lock.")
    p_gc.add_argument("--locks-dir", default=".", help="Directory to scan for *.lock (default: .).")
    p_gc.add_argument("--dry-run", action="store_true", help="List orphans only (the default).")
    p_gc.add_argument("--delete", action="store_true", help="Delete orphans after confirmation.")
    _add_common(p_gc)

    # --- update ---
    p_update = sub.add_parser("update", help="Refresh pinned commits/hashes/params in place.")
    p_update.add_argument("lock", help="Path to the lockfile.")
    p_update.add_argument("--nodes", action="store_true", help="Update git node commits.")
    p_update.add_argument("--models", action="store_true", help="Re-hash models on disk.")
    p_update.add_argument("--params", action="store_true", help="Re-scan workflow parameters.")
    p_update.add_argument("-o", "--out", default=None, help="Output lock (default: overwrite input).")
    p_update.add_argument("--dry-run", action="store_true", help="Print changes, write nothing.")
    _add_common(p_update)

    # --- sign ---
    p_sign = sub.add_parser("sign", help="Sign a lockfile (detached GPG signature).")
    p_sign.add_argument("lock", help="Path to the lockfile.")
    p_sign.add_argument("--key", default=None, help="GPG key id / email to sign with.")
    p_sign.add_argument("--sigstore", action="store_true", help="Use Sigstore keyless signing (extra).")

    # --- init ---
    sub.add_parser("init", help="Interactive setup wizard.")

    # --- completions ---
    from .completions import SHELLS

    p_comp = sub.add_parser("completions", help="Emit a shell completion script.")
    p_comp.add_argument("--shell", required=True, choices=SHELLS, help="Target shell.")

    sub.add_parser("selftest", help="Run the built-in self-test suite.")

    return parser


def _cache(disabled: bool, root: str | None) -> HashCache | None:
    if disabled:
        return HashCache()  # in-memory only
    base = Path(root) if root else Path(".")
    return HashCache(base / DEFAULT_CACHE)


def cmd_pack(args: argparse.Namespace) -> int:
    cache_path = None if args.no_cache else (Path(args.comfyui_root or ".") / DEFAULT_CACHE)
    out = do_pack(
        args.workflow,
        out_path=args.out,
        comfyui_root=args.comfyui_root,
        hash_types=args.hash,
        cache_path=cache_path,
        lock_version=args.lock_version,
        strict=args.strict,
        provenance=args.provenance,
    )
    print(f"Wrote {out}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    if args.check_sig:
        from .sign import verify_signature

        ok, msg = verify_signature(args.lock)
        if not ok:
            print(f"error: signature check failed: {msg}", file=sys.stderr)
            return 2
        print(f"signature: {msg}")
    lock = serialize.read(args.lock)
    report = do_verify(
        lock,
        comfyui_root=args.comfyui_root,
        check_hashes=not args.no_hash,
        cache=_cache(args.no_cache, args.comfyui_root),
    )
    print(report.render())
    if not report.passed:
        return 1
    if args.strict and report.n_warnings:
        print(f"\nstrict: {report.n_warnings} warning(s) treated as failure.", file=sys.stderr)
        return 1
    return 0


def cmd_unpack(args: argparse.Namespace) -> int:
    if args.comfyui_root is None:
        print("error: --comfyui-root is required for unpack.", file=sys.stderr)
        return 2
    lock = serialize.read(args.lock)
    result = do_unpack(
        lock,
        comfyui_root=args.comfyui_root,
        dry_run=not args.apply,
        download_models=not args.no_models,
        jobs=max(1, args.jobs),
    )
    print(result.render())
    if not args.apply:
        print("\n(dry run - re-run with --apply to perform these actions)")
    return 1 if result.errors else 0


def cmd_diff(args: argparse.Namespace) -> int:
    old = serialize.read(args.old)
    new = serialize.read(args.new)
    d = diff_locks(old, new)
    print(d.render())
    return 1 if (args.exit_code and not d.empty) else 0


def cmd_inspect(args: argparse.Namespace) -> int:
    from .inspect import inspect_json, inspect_text

    lock = serialize.read(args.lock)
    if args.json:
        sys.stdout.write(inspect_json(lock))
        return 0
    color = (not args.no_color) and sys.stdout.isatty()
    print(inspect_text(lock, color=color))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from .exporters import export

    lock = serialize.read(args.lock)
    text = export(lock, args.format)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_manager_import(args: argparse.Namespace) -> int:
    from .manager_import import manager_import

    out, warnings = manager_import(args.snapshot, out_path=args.out, comfyui_root=args.comfyui_root)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(f"Wrote {out}")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    from .merge import merge_locks

    locks = [serialize.read(p) for p in args.locks]
    merged, warnings = merge_locks(locks, strategy=args.strategy)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    out = serialize.write(merged, args.out)
    print(f"Wrote {out}")
    return 0


def cmd_gc(args: argparse.Namespace) -> int:
    if args.comfyui_root is None:
        print("error: --comfyui-root is required for gc.", file=sys.stderr)
        return 2
    from .gc import delete_orphans, find_orphans

    result = find_orphans(args.comfyui_root, locks_dir=args.locks_dir)
    print(result.render())
    if args.delete and result.orphans:
        if not sys.stdin.isatty():
            print("\nrefusing to delete in a non-interactive session.", file=sys.stderr)
            return 2
        answer = input(f"\nDelete {len(result.orphans)} file(s)? [y/N] ").strip().lower()
        if answer == "y":
            removed = delete_orphans(result)
            print(f"Deleted {len(removed)} file(s).")
        else:
            print("Aborted.")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    if args.comfyui_root is None:
        print("error: --comfyui-root is required for update.", file=sys.stderr)
        return 2
    from .update import update_lock, write_update

    lock = serialize.read(args.lock)
    # No selector => update everything.
    any_sel = args.nodes or args.models or args.params
    do_nodes = args.nodes or not any_sel
    do_models = args.models or not any_sel
    do_params = args.params or not any_sel
    new, changes = update_lock(
        lock, args.comfyui_root,
        do_nodes=do_nodes, do_models=do_models, do_params=do_params,
        cache=_cache(False, args.comfyui_root),
    )
    if not changes:
        print("Already up to date.")
        return 0
    for ch in changes:
        print(f"  {ch}")
    if args.dry_run:
        print("\n(dry run - nothing written)")
        return 0
    out = write_update(new, args.out or args.lock)
    print(f"Wrote {out}")
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    from .sign import sign_lock

    sig = sign_lock(args.lock, key=args.key, sigstore=args.sigstore)
    print(f"Wrote {sig}")
    return 0


def cmd_init(_args: argparse.Namespace) -> int:
    from .init import run_init

    return run_init()


def cmd_completions(args: argparse.Namespace) -> int:
    from .completions import completion_script

    sys.stdout.write(completion_script(args.shell))
    return 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    from .selftest import run_selftest

    return run_selftest()


def _force_utf8() -> None:
    """Emit UTF-8 regardless of the console codepage.

    ``inspect`` and the Markdown export use a few non-ASCII glyphs (✓, ·, …).
    On a Windows console (cp1252) writing them would raise UnicodeEncodeError, so
    switch stdout/stderr to UTF-8 where the runtime allows it.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):  # pragma: no cover - platform dependent
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "pack": cmd_pack,
        "verify": cmd_verify,
        "unpack": cmd_unpack,
        "diff": cmd_diff,
        "inspect": cmd_inspect,
        "export": cmd_export,
        "manager-import": cmd_manager_import,
        "merge": cmd_merge,
        "gc": cmd_gc,
        "update": cmd_update,
        "sign": cmd_sign,
        "init": cmd_init,
        "completions": cmd_completions,
        "selftest": cmd_selftest,
    }
    try:
        return handlers[args.command](args)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
