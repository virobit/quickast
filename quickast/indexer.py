"""Core indexer — scans Python files and populates the SQLite index."""

import os
import sqlite3
import sys
from pathlib import Path

from .db import get_db, init_db, find_db_path
from .parser import parse_file

# Directories to always skip
DEFAULT_EXCLUDE_DIRS = {
    "venv", ".venv", "env", ".env",
    "__pycache__", ".git", "node_modules",
    ".mypy_cache", ".pytest_cache", ".tox", ".nox",
    "dist", "build", ".eggs", "*.egg-info",
    ".cache", ".ruff_cache",
}


class Indexer:
    """Indexes Python files into the QuickAST SQLite database."""

    def __init__(self, project_root: Path, db_path: Path | None = None,
                 exclude_dirs: set[str] | None = None):
        self.project_root = project_root.resolve()
        self.db_path = db_path or find_db_path(self.project_root)
        self.exclude_dirs = exclude_dirs or DEFAULT_EXCLUDE_DIRS
        init_db(self.db_path)

    def should_skip(self, path: Path) -> bool:
        """Check if a path should be excluded from indexing."""
        try:
            parts = path.relative_to(self.project_root).parts
            return any(p in self.exclude_dirs for p in parts)
        except ValueError:
            return True

    def find_python_files(self) -> list[Path]:
        """Walk the project tree and find all Python files."""
        files = []
        for root, dirs, filenames in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in self.exclude_dirs]
            for f in filenames:
                if f.endswith(".py"):
                    fp = Path(root) / f
                    if not self.should_skip(fp):
                        files.append(fp)
        return files

    def index_file(self, filepath: Path, conn: sqlite3.Connection | None = None) -> bool:
        """Index a single file. Returns True if file was (re)indexed."""
        if not filepath.exists() or self.should_skip(filepath):
            return False

        own_conn = conn is None
        if own_conn:
            conn = get_db(self.db_path)

        try:
            stat = filepath.stat()
            relative = str(filepath.relative_to(self.project_root))

            existing = conn.execute(
                "SELECT id, mtime FROM files WHERE path = ?", (str(filepath),)
            ).fetchone()

            if existing and existing["mtime"] >= stat.st_mtime:
                return False

            parsed = parse_file(filepath)

            if existing:
                conn.execute("DELETE FROM files WHERE id = ?", (existing["id"],))

            cursor = conn.execute(
                """INSERT INTO files (path, relative_path, mtime, size, line_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(filepath), relative, stat.st_mtime, stat.st_size, parsed["line_count"]),
            )
            file_id = cursor.lastrowid

            self._insert_symbols(conn, file_id, parsed["symbols"], parent_id=None)

            for imp in parsed["imports"]:
                conn.execute(
                    """INSERT INTO imports (file_id, module, name, alias, line)
                       VALUES (?, ?, ?, ?, ?)""",
                    (file_id, imp["module"], imp["name"], imp["alias"], imp["line"]),
                )

            for call in parsed["calls"]:
                conn.execute(
                    """INSERT INTO call_references (file_id, caller_qualified,
                       callee_name, callee_type, callee_object, line)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (file_id, call["caller"], call["callee_name"],
                     call["callee_type"], call.get("callee_object"), call["line"]),
                )

            for route in parsed["routes"]:
                conn.execute(
                    """INSERT INTO api_routes (file_id, route_type, path, method,
                       handler_function, handler_qualified, line, description,
                       service, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (file_id, route["route_type"], route["path"], route.get("method"),
                     route["handler"], route.get("qualified"), route["line"],
                     route.get("description"), None, route.get("extra")),
                )

            conn.commit()
            return True
        finally:
            if own_conn:
                conn.close()

    def _insert_symbols(self, conn: sqlite3.Connection, file_id: int,
                        symbols: list, parent_id: int | None):
        """Recursively insert symbols into the database."""
        for sym in symbols:
            cursor = conn.execute(
                """INSERT INTO symbols (file_id, name, qualified_name, type, line,
                   end_line, signature, docstring, parent_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (file_id, sym["name"], sym["qualified_name"], sym["type"],
                 sym["line"], sym.get("end_line"), sym["signature"],
                 sym.get("docstring"), parent_id),
            )
            sym_id = cursor.lastrowid
            if sym.get("children"):
                self._insert_symbols(conn, file_id, sym["children"], parent_id=sym_id)

    def remove_file(self, filepath: Path):
        """Remove a file and all its symbols from the index."""
        conn = get_db(self.db_path)
        try:
            conn.execute("DELETE FROM files WHERE path = ?", (str(filepath),))
            conn.commit()
        finally:
            conn.close()

    def build(self, verbose: bool = True) -> dict:
        """Full index build. Returns statistics."""
        files = self.find_python_files()
        indexed = skipped = errors = 0
        conn = get_db(self.db_path)

        try:
            for f in files:
                try:
                    if self.index_file(f, conn=conn):
                        indexed += 1
                    else:
                        skipped += 1
                except Exception as e:
                    errors += 1
                    if verbose:
                        print(f"  Error indexing {f}: {e}", file=sys.stderr)

            removed = self._cleanup_deleted(conn)
        finally:
            conn.close()

        return {
            "total_files": len(files), "indexed": indexed,
            "skipped": skipped, "errors": errors, "removed": removed,
        }

    def _cleanup_deleted(self, conn: sqlite3.Connection) -> int:
        """Remove entries for files that no longer exist on disk."""
        rows = conn.execute("SELECT id, path FROM files").fetchall()
        removed = 0
        for row in rows:
            if not Path(row["path"]).exists():
                conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))
                removed += 1
        if removed:
            conn.commit()
        return removed
