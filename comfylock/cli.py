"""Command-line interface: ``comfy-lock <pack|verify|unpack|diff> ...``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, serialize
from .diff import diff as diff_locks
from .hashes import COMPUTABLE, HashCache
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
    parser.add_argument("--version", action="version", version=f"comfylock {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pack = sub.add_parser("pack", help="Create a lockfile from a workflow.")
    p_pack.add_argument("workflow", help="Path to the workflow .json / .flow.json.")
    p_pack.add_argument("-o", "--out", default=None, help="Output lock path (default: <workflow>.lock).")
    p_pack.add_argument(
        "--hash",
        action="append",
        default=None,
        metavar="TYPE",
        help=f"Hash type(s) to record. Repeatable. One of: {', '.join(COMPUTABLE)}.",
    )
    p_pack.add_argument("--no-cache", action="store_true", help="Disable the hash cache.")
    _add_common(p_pack)

    p_verify = sub.add_parser("verify", help="Check the environment against a lockfile.")
    p_verify.add_argument("lock", help="Path to the lockfile.")
    p_verify.add_argument("--no-hash", action="store_true", help="Skip model hashing (fast).")
    p_verify.add_argument("--no-cache", action="store_true", help="Disable the hash cache.")
    _add_common(p_verify)

    p_unpack = sub.add_parser("unpack", help="Fetch missing nodes/models from a lockfile.")
    p_unpack.add_argument("lock", help="Path to the lockfile.")
    p_unpack.add_argument(
        "--apply",
        action="store_true",
        help="Actually perform actions (default is a dry run).",
    )
    p_unpack.add_argument("--no-models", action="store_true", help="Do not download models.")
    _add_common(p_unpack)

    p_diff = sub.add_parser("diff", help="Show semantic changes between two lockfiles.")
    p_diff.add_argument("old", help="Old lockfile.")
    p_diff.add_argument("new", help="New lockfile.")

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
    )
    print(f"Wrote {out}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    lock = serialize.read(args.lock)
    report = do_verify(
        lock,
        comfyui_root=args.comfyui_root,
        check_hashes=not args.no_hash,
        cache=_cache(args.no_cache, args.comfyui_root),
    )
    print(report.render())
    return 0 if report.passed else 1


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
    return 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    from .selftest import run_selftest

    return run_selftest()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "pack": cmd_pack,
        "verify": cmd_verify,
        "unpack": cmd_unpack,
        "diff": cmd_diff,
        "selftest": cmd_selftest,
    }
    try:
        return handlers[args.command](args)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
