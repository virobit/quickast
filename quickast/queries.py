"""Query interface for the QuickAST index."""

import time
from datetime import datetime
from pathlib import Path

from .db import get_db


def _resolve_file(conn, path: str) -> int | None:
    """Resolve a file path (relative or absolute) to its database ID."""
    row = conn.execute(
        "SELECT id FROM files WHERE relative_path = ? OR path = ?", (path, path)
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        "SELECT id FROM files WHERE relative_path LIKE ? ORDER BY LENGTH(relative_path) LIMIT 1",
        (f"%/{path}" if "/" not in path else f"%{path}",),
    ).fetchone()
    return row["id"] if row else None


def query_symbol(db_path: Path, name: str) -> list[dict]:
    """Find symbol definitions by exact name."""
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            """SELECT s.name, s.qualified_name, s.type, s.line, s.end_line,
                      s.signature, s.docstring, f.relative_path
               FROM symbols s JOIN files f ON s.file_id = f.id
               WHERE s.name = ? ORDER BY f.relative_path, s.line""",
            (name,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def search_symbols(db_path: Path, pattern: str) -> list[dict]:
    """Search symbols with wildcard support (% for any characters)."""
    conn = get_db(db_path)
    try:
        if "%" not in pattern:
            pattern = f"%{pattern}%"
        rows = conn.execute(
            """SELECT s.name, s.qualified_name, s.type, s.line, s.signature,
                      f.relative_path
               FROM symbols s JOIN files f ON s.file_id = f.id
               WHERE s.name LIKE ? OR s.qualified_name LIKE ?
               ORDER BY f.relative_path, s.line LIMIT 50""",
            (pattern, pattern),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_references(db_path: Path, name: str) -> list[dict]:
    """Find all files that import a symbol."""
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            """SELECT f.relative_path, i.module, i.name, i.alias, i.line
               FROM imports i JOIN files f ON i.file_id = f.id
               WHERE i.name = ? ORDER BY f.relative_path, i.line""",
            (name,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_file_symbols(db_path: Path, path: str) -> list[dict]:
    """List all symbols defined in a specific file."""
    conn = get_db(db_path)
    try:
        file_id = _resolve_file(conn, path)
        if not file_id:
            return []
        rows = conn.execute(
            """SELECT s.name, s.qualified_name, s.type, s.line, s.end_line,
                      s.signature, s.docstring
               FROM symbols s WHERE s.file_id = ?
               ORDER BY s.line""",
            (file_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_callees(db_path: Path, qualified_name: str) -> list[dict]:
    """What does this function/method call?"""
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            """SELECT callee_name, callee_type, callee_object, line
               FROM call_references WHERE caller_qualified = ?
               ORDER BY line""",
            (qualified_name,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_callers_of(db_path: Path, callee_name: str) -> list[dict]:
    """What calls this function? Returns unique caller + file pairs."""
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            """SELECT DISTINCT c.caller_qualified, c.callee_type, c.line,
                      f.relative_path
               FROM call_references c JOIN files f ON c.file_id = f.id
               WHERE c.callee_name = ?
               ORDER BY f.relative_path, c.line""",
            (callee_name,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_impact(db_path: Path, name: str, depth: int = 3) -> dict:
    """Transitive impact analysis — upstream callers and downstream callees."""
    conn = get_db(db_path)
    try:
        # Downstream: what does name call (transitively)
        downstream = set()
        frontier = {name}
        for _ in range(depth):
            next_frontier = set()
            for fn in frontier:
                rows = conn.execute(
                    "SELECT DISTINCT callee_name FROM call_references WHERE caller_qualified = ?",
                    (fn,),
                ).fetchall()
                for r in rows:
                    cn = r["callee_name"]
                    if cn not in downstream and cn not in frontier:
                        next_frontier.add(cn)
                        downstream.add(cn)
            frontier = next_frontier
            if not frontier:
                break

        # Upstream: what calls name (transitively)
        upstream = set()
        frontier = {name}
        for _ in range(depth):
            next_frontier = set()
            for fn in frontier:
                rows = conn.execute(
                    "SELECT DISTINCT caller_qualified FROM call_references WHERE callee_name = ?",
                    (fn,),
                ).fetchall()
                for r in rows:
                    cq = r["caller_qualified"]
                    if cq not in upstream and cq not in frontier:
                        next_frontier.add(cq)
                        upstream.add(cq)
            frontier = next_frontier
            if not frontier:
                break

        return {
            "name": name,
            "upstream_callers": sorted(upstream),
            "downstream_callees": sorted(downstream),
        }
    finally:
        conn.close()


def query_routes(db_path: Path, route_type: str = None) -> list[dict]:
    """List API routes, optionally filtered by type."""
    conn = get_db(db_path)
    try:
        sql = """SELECT r.*, f.relative_path FROM api_routes r
                 LEFT JOIN files f ON r.file_id = f.id WHERE 1=1"""
        params = []
        if route_type:
            sql += " AND r.route_type = ?"
            params.append(route_type)
        sql += " ORDER BY r.path"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_route(db_path: Path, path: str) -> list[dict]:
    """Find a specific route by path (supports partial matching)."""
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            """SELECT r.*, f.relative_path FROM api_routes r
               LEFT JOIN files f ON r.file_id = f.id
               WHERE r.path = ? OR r.path LIKE ?
               ORDER BY r.path""",
            (path, f"%{path}%"),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_changes(db_path: Path, hours: int = 24) -> list[dict]:
    """List files changed within the given number of hours."""
    conn = get_db(db_path)
    try:
        cutoff = time.time() - (hours * 3600)
        rows = conn.execute(
            """SELECT f.relative_path, f.mtime, f.size, f.line_count,
                      COUNT(s.id) as symbol_count
               FROM files f LEFT JOIN symbols s ON s.file_id = f.id
               WHERE f.mtime > ?
               GROUP BY f.id ORDER BY f.mtime DESC""",
            (cutoff,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["modified"] = datetime.fromtimestamp(d["mtime"]).strftime("%Y-%m-%d %H:%M")
            results.append(d)
        return results
    finally:
        conn.close()


def query_summary(db_path: Path, path: str) -> dict | None:
    """Get a summary of a module (symbol counts, top symbols, etc.)."""
    conn = get_db(db_path)
    try:
        file_id = _resolve_file(conn, path)
        if not file_id:
            return None
        file_row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()

        counts = conn.execute(
            "SELECT type, COUNT(*) as cnt FROM symbols WHERE file_id = ? GROUP BY type",
            (file_id,),
        ).fetchall()

        import_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM imports WHERE file_id = ?", (file_id,),
        ).fetchone()["cnt"]

        top_symbols = conn.execute(
            """SELECT name, type, line, signature FROM symbols
               WHERE file_id = ? AND parent_id IS NULL
               ORDER BY line LIMIT 30""",
            (file_id,),
        ).fetchall()

        return {
            "file": file_row["relative_path"], "size": file_row["size"],
            "lines": file_row["line_count"],
            "symbol_counts": {r["type"]: r["cnt"] for r in counts},
            "import_count": import_count,
            "top_symbols": [dict(r) for r in top_symbols],
        }
    finally:
        conn.close()


def get_stats(db_path: Path) -> dict:
    """Get overall index statistics."""
    conn = get_db(db_path)
    try:
        files = conn.execute("SELECT COUNT(*) as cnt FROM files").fetchone()["cnt"]
        symbols = conn.execute("SELECT COUNT(*) as cnt FROM symbols").fetchone()["cnt"]
        imports = conn.execute("SELECT COUNT(*) as cnt FROM imports").fetchone()["cnt"]
        calls = conn.execute("SELECT COUNT(*) as cnt FROM call_references").fetchone()["cnt"]
        routes = conn.execute("SELECT COUNT(*) as cnt FROM api_routes").fetchone()["cnt"]

        by_type = conn.execute(
            "SELECT type, COUNT(*) as cnt FROM symbols GROUP BY type ORDER BY cnt DESC"
        ).fetchall()

        largest = conn.execute(
            """SELECT relative_path, line_count, size FROM files
               ORDER BY line_count DESC LIMIT 5"""
        ).fetchall()

        total_lines = conn.execute(
            "SELECT SUM(line_count) as total FROM files"
        ).fetchone()["total"] or 0

        route_types = conn.execute(
            "SELECT route_type, COUNT(*) as cnt FROM api_routes GROUP BY route_type"
        ).fetchall()

        return {
            "files": files, "symbols": symbols, "imports": imports,
            "calls": calls, "routes": routes, "total_lines": total_lines,
            "by_type": {r["type"]: r["cnt"] for r in by_type},
            "route_types": {r["route_type"]: r["cnt"] for r in route_types},
            "largest_files": [dict(r) for r in largest],
        }
    finally:
        conn.close()
