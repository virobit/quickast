"""Database connection and initialization for QuickAST."""

import sqlite3
from pathlib import Path

from .schema import SCHEMA

DEFAULT_DB_NAME = ".quickast.db"


def find_db_path(project_root: Path) -> Path:
    """Return the path to the QuickAST database for a project."""
    return project_root / DEFAULT_DB_NAME


def get_db(db_path: Path) -> sqlite3.Connection:
    """Open a connection to the QuickAST database."""
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    """Initialize the database schema."""
    conn = get_db(db_path)
    conn.executescript(SCHEMA)
    conn.close()
