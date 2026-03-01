"""Core tests for QuickAST — parsing, indexing, and queries."""

import tempfile
from pathlib import Path

import pytest

from quickast.db import find_db_path, get_db, init_db
from quickast.indexer import Indexer
from quickast.parser import parse_file
from quickast.queries import (
    get_stats, query_callers_of, query_callees, query_file_symbols,
    query_impact, query_references, query_routes, query_summary,
    query_symbol, search_symbols,
)


SAMPLE_CODE = '''\
"""Sample module for testing."""

import os
from pathlib import Path


class UserManager:
    """Manages user operations."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def create_user(self, name: str, email: str) -> dict:
        """Create a new user."""
        self._validate_email(email)
        record = {"name": name, "email": email}
        self._save(record)
        return record

    def _validate_email(self, email: str) -> bool:
        return "@" in email

    def _save(self, record: dict):
        pass


def get_manager(db_path: str = "/tmp/test.db") -> UserManager:
    """Factory function for UserManager."""
    return UserManager(db_path)


async def async_handler(request):
    """An async function."""
    mgr = get_manager()
    return mgr.create_user("test", "test@example.com")
'''

SAMPLE_FASTAPI = '''\
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()


@app.get("/api/users")
async def list_users():
    """List all users."""
    return []


@app.post("/api/users")
async def create_user(name: str):
    """Create a user."""
    return {"name": name}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """Main dashboard."""
    return "<h1>Dashboard</h1>"
'''


@pytest.fixture
def project_dir(tmp_path):
    """Create a temporary project with sample Python files."""
    (tmp_path / "app.py").write_text(SAMPLE_CODE)
    (tmp_path / "routes.py").write_text(SAMPLE_FASTAPI)
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "helper.py").write_text(
        "from app import UserManager\n\ndef helper():\n    pass\n"
    )
    return tmp_path


@pytest.fixture
def indexed_project(project_dir):
    """Create and index a temporary project."""
    indexer = Indexer(project_dir)
    indexer.build(verbose=False)
    return project_dir, indexer.db_path


class TestParser:
    def test_parse_symbols(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(SAMPLE_CODE)
        result = parse_file(f)
        names = [s["name"] for s in result["symbols"]]
        assert "UserManager" in names
        assert "get_manager" in names
        assert "async_handler" in names

    def test_parse_class_methods(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(SAMPLE_CODE)
        result = parse_file(f)
        cls = [s for s in result["symbols"] if s["name"] == "UserManager"][0]
        method_names = [c["name"] for c in cls["children"]]
        assert "__init__" in method_names
        assert "create_user" in method_names
        assert "_validate_email" in method_names

    def test_parse_imports(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(SAMPLE_CODE)
        result = parse_file(f)
        modules = [i["module"] for i in result["imports"]]
        assert "os" in modules
        assert "pathlib" in modules

    def test_parse_calls(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(SAMPLE_CODE)
        result = parse_file(f)
        callee_names = [c["callee_name"] for c in result["calls"]]
        assert "_validate_email" in callee_names
        assert "_save" in callee_names
        assert "UserManager" in callee_names

    def test_parse_routes(self, tmp_path):
        f = tmp_path / "routes.py"
        f.write_text(SAMPLE_FASTAPI)
        result = parse_file(f)
        paths = [r["path"] for r in result["routes"]]
        assert "/api/users" in paths
        assert "/dashboard" in paths

    def test_parse_page_route(self, tmp_path):
        f = tmp_path / "routes.py"
        f.write_text(SAMPLE_FASTAPI)
        result = parse_file(f)
        dashboard = [r for r in result["routes"] if r["path"] == "/dashboard"][0]
        assert dashboard["route_type"] == "page"

    def test_parse_syntax_error(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def broken(\n")
        result = parse_file(f)
        assert result["symbols"] == []
        assert result["line_count"] > 0

    def test_parse_nonexistent(self, tmp_path):
        f = tmp_path / "missing.py"
        result = parse_file(f)
        assert result["symbols"] == []

    def test_line_count(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(SAMPLE_CODE)
        result = parse_file(f)
        assert result["line_count"] > 30


class TestIndexer:
    def test_build(self, project_dir):
        indexer = Indexer(project_dir)
        stats = indexer.build(verbose=False)
        assert stats["total_files"] == 3
        assert stats["indexed"] == 3
        assert stats["errors"] == 0

    def test_incremental(self, project_dir):
        indexer = Indexer(project_dir)
        indexer.build(verbose=False)
        stats = indexer.build(verbose=False)
        assert stats["indexed"] == 0
        assert stats["skipped"] == 3

    def test_reindex_on_change(self, project_dir):
        indexer = Indexer(project_dir)
        indexer.build(verbose=False)
        import time
        time.sleep(0.1)
        (project_dir / "app.py").write_text(SAMPLE_CODE + "\n# modified\n")
        stats = indexer.build(verbose=False)
        assert stats["indexed"] == 1

    def test_exclude_venv(self, project_dir):
        venv = project_dir / "venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "something.py").write_text("x = 1\n")
        indexer = Indexer(project_dir)
        files = indexer.find_files()
        rel_paths = [str(f.relative_to(project_dir)) for f in files]
        assert not any(p.startswith("venv/") for p in rel_paths)

    def test_cleanup_deleted(self, project_dir):
        indexer = Indexer(project_dir)
        indexer.build(verbose=False)
        (project_dir / "subdir" / "helper.py").unlink()
        stats = indexer.build(verbose=False)
        assert stats["removed"] == 1


class TestQueries:
    def test_query_symbol(self, indexed_project):
        _, db_path = indexed_project
        results = query_symbol(db_path, "UserManager")
        assert len(results) == 1
        assert results[0]["type"] == "class"

    def test_search_symbols(self, indexed_project):
        _, db_path = indexed_project
        results = search_symbols(db_path, "%user%")
        names = [r["name"] for r in results]
        assert any("user" in n.lower() for n in names)

    def test_query_references(self, indexed_project):
        _, db_path = indexed_project
        results = query_references(db_path, "UserManager")
        assert len(results) >= 1
        assert any("helper" in r["relative_path"] for r in results)

    def test_query_file_symbols(self, indexed_project):
        _, db_path = indexed_project
        results = query_file_symbols(db_path, "app.py")
        names = [r["name"] for r in results]
        assert "UserManager" in names
        assert "get_manager" in names

    def test_query_callees(self, indexed_project):
        _, db_path = indexed_project
        results = query_callees(db_path, "UserManager.create_user")
        callee_names = [r["callee_name"] for r in results]
        assert "_validate_email" in callee_names
        assert "_save" in callee_names

    def test_query_callers_of(self, indexed_project):
        _, db_path = indexed_project
        results = query_callers_of(db_path, "get_manager")
        assert len(results) >= 1
        callers = [r["caller_qualified"] for r in results]
        assert "async_handler" in callers

    def test_query_impact(self, indexed_project):
        _, db_path = indexed_project
        result = query_impact(db_path, "UserManager.create_user")
        assert "_validate_email" in result["downstream_callees"]
        assert "_save" in result["downstream_callees"]

    def test_query_routes(self, indexed_project):
        _, db_path = indexed_project
        results = query_routes(db_path)
        paths = [r["path"] for r in results]
        assert "/api/users" in paths

    def test_query_summary(self, indexed_project):
        _, db_path = indexed_project
        result = query_summary(db_path, "app.py")
        assert result is not None
        assert result["lines"] > 0
        assert "class" in result["symbol_counts"]

    def test_get_stats(self, indexed_project):
        _, db_path = indexed_project
        stats = get_stats(db_path)
        assert stats["files"] == 3
        assert stats["symbols"] > 5
        assert stats["calls"] > 0
        assert stats["imports"] > 0
