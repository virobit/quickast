"""Command-line interface for QuickAST."""

import sys
from pathlib import Path

from .db import find_db_path
from .indexer import Indexer
from .queries import (
    get_stats, query_callers_of, query_callees, query_changes,
    query_file_symbols, query_impact, query_references, query_route,
    query_routes, query_summary, query_symbol, search_symbols,
)

USAGE = """\
QuickAST — Instant codebase intelligence for AI coding agents.

Usage:
    quickast init                       Build the index for the current directory
    quickast watch [options]             Start the file watcher
        --daemon, -d                       Run in background
        --debounce N                       Seconds to wait before re-indexing (default: 2)
        --nice                             Lower CPU priority (nice 10)
    quickast stop                       Stop the background watcher
    quickast query <name>               Find where a symbol is defined
    quickast search <pattern>           Fuzzy search symbols (use % wildcards)
    quickast refs <name>                Find all files that import a symbol
    quickast file <path>                List all symbols defined in a file
    quickast callees <qualified_name>   What does function X call?
    quickast callers-of <name>          What calls function X?
    quickast impact <name> [depth]      Transitive impact analysis
    quickast routes [--type TYPE]       List API routes
    quickast route <path>               Find a specific route
    quickast changes [hours]            Files changed recently (default: 24h)
    quickast summary <path>             Module overview
    quickast stats                      Index statistics
    quickast version                    Show version
"""


def _find_project_root() -> Path:
    """Walk up from cwd to find the project root (directory with .git or pyproject.toml)."""
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return cwd


def _get_db_path() -> Path:
    return find_db_path(_find_project_root())


def _ensure_index(db_path: Path):
    if not db_path.exists():
        print("No QuickAST index found. Run 'quickast init' first.")
        sys.exit(1)


def cmd_init():
    root = _find_project_root()
    print(f"Indexing {root}...")
    indexer = Indexer(root)
    stats = indexer.build()
    print(f"\nDone! Indexed {stats['total_files']} files:")
    print(f"  {stats['indexed']} indexed, {stats['skipped']} unchanged, "
          f"{stats['errors']} errors, {stats['removed']} removed")
    s = get_stats(indexer.db_path)
    print(f"\n  {s['symbols']:,} symbols | {s['calls']:,} call refs | "
          f"{s['imports']:,} imports | {s['routes']} routes | "
          f"{s['total_lines']:,} lines of code")
    print(f"\nIndex saved to: {indexer.db_path}")


def cmd_watch(args: list[str]):
    from .watcher import start_watcher, DEFAULT_DEBOUNCE
    root = _find_project_root()
    daemon = "--daemon" in args or "-d" in args
    nice = "--nice" in args
    debounce = DEFAULT_DEBOUNCE
    if "--debounce" in args:
        idx = args.index("--debounce")
        if idx + 1 < len(args):
            try:
                debounce = float(args[idx + 1])
            except ValueError:
                print("Error: --debounce requires a number (seconds).")
                return
    start_watcher(root, daemon=daemon, debounce=debounce, nice=nice)


def cmd_stop():
    root = _find_project_root()
    pid_file = root / ".quickast.pid"
    if not pid_file.exists():
        print("No watcher running (no .quickast.pid file found).")
        return
    try:
        pid = int(pid_file.read_text().strip())
        import os
        os.kill(pid, 15)  # SIGTERM
        print(f"Stopped watcher (PID {pid}).")
    except ProcessLookupError:
        print("Watcher process not found (stale PID file). Cleaning up.")
        pid_file.unlink(missing_ok=True)
    except Exception as e:
        print(f"Error stopping watcher: {e}")


def cmd_query(args: list[str]):
    db_path = _get_db_path()
    _ensure_index(db_path)
    if not args:
        print("Usage: quickast query <symbol_name>")
        return
    results = query_symbol(db_path, args[0])
    if not results:
        print(f"No matches: {args[0]}")
        return
    for r in results:
        sig = r.get("signature") or r["name"]
        print(f"  {r['type']:8s} {r['relative_path']}:{r['line']}  {sig}")


def cmd_search(args: list[str]):
    db_path = _get_db_path()
    _ensure_index(db_path)
    if not args:
        print("Usage: quickast search <pattern>")
        return
    results = search_symbols(db_path, args[0])
    if not results:
        print(f"No matches: {args[0]}")
        return
    for r in results:
        sig = r.get("signature") or r["name"]
        print(f"  {r['type']:8s} {r['relative_path']}:{r['line']}  {sig}")


def cmd_refs(args: list[str]):
    db_path = _get_db_path()
    _ensure_index(db_path)
    if not args:
        print("Usage: quickast refs <symbol_name>")
        return
    results = query_references(db_path, args[0])
    if not results:
        print(f"No imports found for: {args[0]}")
        return
    print(f"{args[0]} is imported by {len(results)} file(s):")
    for r in results:
        alias_str = f" as {r['alias']}" if r.get("alias") else ""
        print(f"  {r['relative_path']}:{r['line']}  from {r['module']} import {r['name']}{alias_str}")


def cmd_file(args: list[str]):
    db_path = _get_db_path()
    _ensure_index(db_path)
    if not args:
        print("Usage: quickast file <path>")
        return
    results = query_file_symbols(db_path, args[0])
    if not results:
        print(f"No symbols found in: {args[0]}")
        return
    for r in results:
        indent = "    " if "." in (r.get("qualified_name") or "") else "  "
        sig = r.get("signature") or r["name"]
        print(f"{indent}{r['type']:8s} L{r['line']:>5d}  {sig}")


def cmd_callees(args: list[str]):
    db_path = _get_db_path()
    _ensure_index(db_path)
    if not args:
        print("Usage: quickast callees <qualified_name>")
        return
    results = query_callees(db_path, args[0])
    if not results:
        print(f"No callees found for: {args[0]}")
        return
    print(f"{args[0]} calls {len(results)} functions:")
    for r in results:
        obj = f"{r['callee_object']}." if r.get("callee_object") else ""
        print(f"  L{r['line']:>5d}  {obj}{r['callee_name']} ({r['callee_type']})")


def cmd_callers_of(args: list[str]):
    db_path = _get_db_path()
    _ensure_index(db_path)
    if not args:
        print("Usage: quickast callers-of <name>")
        return
    results = query_callers_of(db_path, args[0])
    if not results:
        print(f"No callers found for: {args[0]}")
        return
    print(f"{args[0]} is called by {len(results)} site(s):")
    for r in results:
        print(f"  {r['relative_path']}:{r['line']}  in {r['caller_qualified']}")


def cmd_impact(args: list[str]):
    db_path = _get_db_path()
    _ensure_index(db_path)
    if not args:
        print("Usage: quickast impact <name> [depth]")
        return
    depth = int(args[1]) if len(args) > 1 else 3
    result = query_impact(db_path, args[0], depth)
    print(f"Impact analysis for {result['name']} (depth={depth}):")
    print(f"\n  Upstream callers ({len(result['upstream_callers'])}):")
    for c in result["upstream_callers"][:20]:
        print(f"    {c}")
    print(f"\n  Downstream callees ({len(result['downstream_callees'])}):")
    for c in result["downstream_callees"][:20]:
        print(f"    {c}")


def cmd_routes(args: list[str]):
    db_path = _get_db_path()
    _ensure_index(db_path)
    route_type = None
    if "--type" in args:
        idx = args.index("--type")
        if idx + 1 < len(args):
            route_type = args[idx + 1]
    results = query_routes(db_path, route_type=route_type)
    if not results:
        print("No routes found.")
        return
    for r in results:
        method = r.get("method") or ""
        rtype = r.get("route_type", "")
        handler = r.get("handler_function", "")
        path = r.get("path", "")
        rel = r.get("relative_path", "")
        line = r.get("line", 0)
        desc = r.get("description") or ""
        print(f"  [{rtype:12s}] {method:6s} {path:40s}")
        print(f"    Handler: {handler} in {rel}:{line}")
        if desc:
            print(f"    Desc: {desc}")


def cmd_route(args: list[str]):
    db_path = _get_db_path()
    _ensure_index(db_path)
    if not args:
        print("Usage: quickast route <path>")
        return
    results = query_route(db_path, args[0])
    if not results:
        print(f"No route found matching: {args[0]}")
        return
    for r in results:
        method = r.get("method") or ""
        handler = r.get("handler_function", "")
        rel = r.get("relative_path", "")
        line = r.get("line", 0)
        print(f"  {method:6s} {r['path']}  ->  {handler} in {rel}:{line}")


def cmd_changes(args: list[str]):
    db_path = _get_db_path()
    _ensure_index(db_path)
    hours = int(args[0]) if args else 24
    results = query_changes(db_path, hours)
    if not results:
        print(f"No files changed in the last {hours} hours.")
        return
    print(f"Files changed in the last {hours} hours:")
    for r in results:
        print(f"  {r['modified']}  {r['relative_path']} ({r['line_count']} lines, {r['symbol_count']} symbols)")


def cmd_summary(args: list[str]):
    db_path = _get_db_path()
    _ensure_index(db_path)
    if not args:
        print("Usage: quickast summary <path>")
        return
    result = query_summary(db_path, args[0])
    if not result:
        print(f"File not found in index: {args[0]}")
        return
    print(f"{result['file']} — {result['lines']} lines, {result['size']} bytes")
    print(f"  Imports: {result['import_count']}")
    for stype, count in result["symbol_counts"].items():
        print(f"  {stype}s: {count}")
    if result["top_symbols"]:
        print(f"\n  Top-level symbols:")
        for s in result["top_symbols"]:
            sig = s.get("signature") or s["name"]
            print(f"    {s['type']:8s} L{s['line']:>5d}  {sig}")


def cmd_stats():
    db_path = _get_db_path()
    _ensure_index(db_path)
    s = get_stats(db_path)
    print(f"QuickAST Index Statistics")
    print(f"  Files:       {s['files']:,}")
    print(f"  Symbols:     {s['symbols']:,}")
    print(f"  Imports:     {s['imports']:,}")
    print(f"  Call refs:   {s['calls']:,}")
    print(f"  Routes:      {s['routes']:,}")
    print(f"  Total lines: {s['total_lines']:,}")
    if s.get("by_type"):
        print(f"\n  Symbol types:")
        for stype, count in s["by_type"].items():
            print(f"    {stype:12s} {count:,}")
    if s.get("route_types"):
        print(f"\n  Route types:")
        for rtype, count in s["route_types"].items():
            print(f"    {rtype:12s} {count:,}")
    if s.get("largest_files"):
        print(f"\n  Largest files:")
        for f in s["largest_files"]:
            print(f"    {f['relative_path']:50s} {f['line_count']:,} lines")


def cmd_version():
    from . import __version__
    print(f"quickast {__version__}")


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE)
        return

    cmd = args[0]
    rest = args[1:]

    commands = {
        "init": lambda: cmd_init(),
        "watch": lambda: cmd_watch(rest),
        "query": lambda: cmd_query(rest),
        "search": lambda: cmd_search(rest),
        "refs": lambda: cmd_refs(rest),
        "file": lambda: cmd_file(rest),
        "callees": lambda: cmd_callees(rest),
        "callers-of": lambda: cmd_callers_of(rest),
        "impact": lambda: cmd_impact(rest),
        "routes": lambda: cmd_routes(rest),
        "route": lambda: cmd_route(rest),
        "changes": lambda: cmd_changes(rest),
        "summary": lambda: cmd_summary(rest),
        "stop": lambda: cmd_stop(),
        "stats": lambda: cmd_stats(),
        "version": lambda: cmd_version(),
        "--version": lambda: cmd_version(),
    }

    if cmd in commands:
        commands[cmd]()
    else:
        print(f"Unknown command: {cmd}")
        print(USAGE)
        sys.exit(1)


if __name__ == "__main__":
    main()
