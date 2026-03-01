"""Core tests for QuickAST — parsing, indexing, and queries."""

import tempfile
from pathlib import Path

import pytest

from quickast.db import find_db_path, get_db, init_db
from quickast.indexer import Indexer
from quickast.parser import parse_file, parse_js_file, parse_markdown_file
from quickast.queries import (
    get_stats, query_callers_of, query_callees, query_file_symbols,
    query_impact, query_references, query_routes, query_summary,
    query_symbol, search_symbols, query_docs, query_doc_sections,
    query_js_files, query_callbacks,
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


# ── v0.3.0 feature test fixtures ────────────────────────────────────

SAMPLE_JS = '''\
class DashboardManager {
    constructor(config) {
        this.config = config;
    }

    async refresh(forceReload) {
        return this.fetchData();
    }

    get isActive() {
        return this.config.active;
    }
}

async function initApp(settings) {
    const mgr = new DashboardManager(settings);
    return mgr;
}

const fetchUsers = async (token) => {
    return fetch("/api/users", { headers: { auth: token } });
};

setInterval(() => { console.log("tick"); }, 5000);

DashboardManager.defaultConfig = function() { return {}; };
'''

SAMPLE_MARKDOWN = '''\
# Project Overview

This is a test project for QuickAST.

## Installation

Run `pip install quickast` to get started.

### From Source

Clone the repo and install in editable mode.

## Usage

Use the CLI commands to query your codebase.

### Advanced Queries

Impact analysis and call graph traversal.
'''

SAMPLE_CALLBACKS = '''\
class Bot:
    def setup(self):
        self.client.set_message_callback(handle_message)
        self.client.set_error_callback(handle_error)
        create_widget(on_click=button_handler, on_hover=hover_handler)

def handle_message(msg):
    pass

def handle_error(err):
    pass

def button_handler():
    pass

def hover_handler():
    pass
'''

SAMPLE_ROUTER_MOUNTS = '''\
from fastapi import FastAPI, APIRouter

app = FastAPI()
user_router = APIRouter()
admin_router = APIRouter()

app.include_router(user_router, prefix="/api/users")
app.include_router(admin_router, prefix="/api/admin")
'''


@pytest.fixture
def multi_type_dir(tmp_path):
    """Project with Python, JS, and Markdown files."""
    (tmp_path / "app.py").write_text(SAMPLE_CODE)
    (tmp_path / "dashboard.js").write_text(SAMPLE_JS)
    (tmp_path / "README.md").write_text(SAMPLE_MARKDOWN)
    return tmp_path


@pytest.fixture
def multi_indexed(multi_type_dir):
    """Index a multi-type project."""
    indexer = Indexer(multi_type_dir)
    indexer.build(verbose=False)
    return multi_type_dir, indexer.db_path


class TestJSParser:
    def test_parse_class(self, tmp_path):
        f = tmp_path / "test.js"
        f.write_text(SAMPLE_JS)
        result = parse_js_file(f)
        names = [s["name"] for s in result["js_symbols"]]
        assert "DashboardManager" in names

    def test_parse_class_is_class_type(self, tmp_path):
        f = tmp_path / "test.js"
        f.write_text(SAMPLE_JS)
        result = parse_js_file(f)
        cls = [s for s in result["js_symbols"] if s["name"] == "DashboardManager"][0]
        assert cls["symbol_type"] == "class"

    def test_parse_methods(self, tmp_path):
        f = tmp_path / "test.js"
        f.write_text(SAMPLE_JS)
        result = parse_js_file(f)
        methods = [s for s in result["js_symbols"] if s["parent_class"] == "DashboardManager"]
        method_names = [m["name"] for m in methods]
        assert "constructor" in method_names
        assert "refresh" in method_names

    def test_parse_getter(self, tmp_path):
        f = tmp_path / "test.js"
        f.write_text(SAMPLE_JS)
        result = parse_js_file(f)
        getters = [s for s in result["js_symbols"] if s["symbol_type"] == "getter"]
        assert len(getters) >= 1
        assert getters[0]["name"] == "isActive"

    def test_parse_function(self, tmp_path):
        f = tmp_path / "test.js"
        f.write_text(SAMPLE_JS)
        result = parse_js_file(f)
        funcs = [s for s in result["js_symbols"] if s["name"] == "initApp"]
        assert len(funcs) == 1
        assert funcs[0]["symbol_type"] == "function"

    def test_parse_arrow_function(self, tmp_path):
        f = tmp_path / "test.js"
        f.write_text(SAMPLE_JS)
        result = parse_js_file(f)
        arrows = [s for s in result["js_symbols"] if s["name"] == "fetchUsers"]
        assert len(arrows) == 1
        assert arrows[0]["symbol_type"] == "arrow_function"

    def test_parse_set_interval(self, tmp_path):
        f = tmp_path / "test.js"
        f.write_text(SAMPLE_JS)
        result = parse_js_file(f)
        intervals = [s for s in result["js_symbols"] if s["symbol_type"] == "setInterval"]
        assert len(intervals) == 1
        assert intervals[0]["interval_ms"] == 5000

    def test_parse_static_method(self, tmp_path):
        f = tmp_path / "test.js"
        f.write_text(SAMPLE_JS)
        result = parse_js_file(f)
        statics = [s for s in result["js_symbols"] if s["symbol_type"] == "static_method"]
        assert len(statics) >= 1
        assert statics[0]["name"] == "defaultConfig"
        assert statics[0]["parent_class"] == "DashboardManager"

    def test_line_count(self, tmp_path):
        f = tmp_path / "test.js"
        f.write_text(SAMPLE_JS)
        result = parse_js_file(f)
        assert result["line_count"] > 10

    def test_nonexistent_file(self, tmp_path):
        f = tmp_path / "missing.js"
        result = parse_js_file(f)
        assert result["js_symbols"] == []


class TestMarkdownParser:
    def test_parse_headings(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(SAMPLE_MARKDOWN)
        result = parse_markdown_file(f)
        headings = [s["heading"] for s in result["sections"]]
        assert "Project Overview" in headings
        assert "Installation" in headings
        assert "Usage" in headings

    def test_heading_levels(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(SAMPLE_MARKDOWN)
        result = parse_markdown_file(f)
        overview = [s for s in result["sections"] if s["heading"] == "Project Overview"][0]
        install = [s for s in result["sections"] if s["heading"] == "Installation"][0]
        from_src = [s for s in result["sections"] if s["heading"] == "From Source"][0]
        assert overview["level"] == 1
        assert install["level"] == 2
        assert from_src["level"] == 3

    def test_parent_hierarchy(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(SAMPLE_MARKDOWN)
        result = parse_markdown_file(f)
        # "From Source" (H3) should have parent_idx pointing to "Installation" (H2)
        from_src = [s for s in result["sections"] if s["heading"] == "From Source"][0]
        assert from_src["parent_idx"] is not None
        parent = result["sections"][from_src["parent_idx"]]
        assert parent["heading"] == "Installation"

    def test_end_lines(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(SAMPLE_MARKDOWN)
        result = parse_markdown_file(f)
        for section in result["sections"]:
            assert section["end_line"] is not None
            assert section["end_line"] >= section["line"]

    def test_fts_entries(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(SAMPLE_MARKDOWN)
        result = parse_markdown_file(f)
        assert len(result["fts_entries"]) == len(result["sections"])
        headings = [e["heading"] for e in result["fts_entries"]]
        assert "Installation" in headings

    def test_line_count(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(SAMPLE_MARKDOWN)
        result = parse_markdown_file(f)
        assert result["line_count"] > 10

    def test_nonexistent_file(self, tmp_path):
        f = tmp_path / "missing.md"
        result = parse_markdown_file(f)
        assert result["sections"] == []
        assert result["fts_entries"] == []


class TestCallbackDetection:
    def test_set_callback_pattern(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(SAMPLE_CALLBACKS)
        result = parse_file(f)
        callbacks = [c for c in result["calls"] if c["callee_type"] == "callback_wire"]
        cb_names = [c["callee_name"] for c in callbacks]
        assert "handle_message" in cb_names
        assert "handle_error" in cb_names

    def test_on_keyword_callback(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(SAMPLE_CALLBACKS)
        result = parse_file(f)
        callbacks = [c for c in result["calls"] if c["callee_type"] == "callback_wire"]
        cb_names = [c["callee_name"] for c in callbacks]
        assert "button_handler" in cb_names
        assert "hover_handler" in cb_names

    def test_callback_has_callee_object(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(SAMPLE_CALLBACKS)
        result = parse_file(f)
        callbacks = [c for c in result["calls"] if c["callee_type"] == "callback_wire"]
        # set_*_callback wirings should have callee_object like "self.client.set_message_callback"
        set_cbs = [c for c in callbacks if c["callee_name"] == "handle_message"]
        assert len(set_cbs) >= 1
        assert set_cbs[0]["callee_object"] is not None
        # on_* wirings should have callee_object like "kwarg:on_click"
        on_cbs = [c for c in callbacks if c["callee_name"] == "button_handler"]
        assert len(on_cbs) >= 1
        assert "kwarg:on_click" in on_cbs[0]["callee_object"]


class TestRouterMountDetection:
    def test_include_router(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(SAMPLE_ROUTER_MOUNTS)
        result = parse_file(f)
        mounts = [r for r in result["routes"] if r["route_type"] == "router_mount"]
        assert len(mounts) == 2

    def test_mount_prefix(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(SAMPLE_ROUTER_MOUNTS)
        result = parse_file(f)
        mounts = [r for r in result["routes"] if r["route_type"] == "router_mount"]
        paths = [m["path"] for m in mounts]
        assert "/api/users" in paths
        assert "/api/admin" in paths

    def test_mount_handler_is_router_name(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(SAMPLE_ROUTER_MOUNTS)
        result = parse_file(f)
        mounts = [r for r in result["routes"] if r["route_type"] == "router_mount"]
        handlers = [m["handler"] for m in mounts]
        assert "user_router" in handlers
        assert "admin_router" in handlers

    def test_mount_extra_json(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(SAMPLE_ROUTER_MOUNTS)
        result = parse_file(f)
        import json
        mounts = [r for r in result["routes"] if r["route_type"] == "router_mount"]
        for m in mounts:
            extra = json.loads(m["extra"])
            assert "app" in extra
            assert "router" in extra
            assert "prefix" in extra


class TestMultiTypeIndexing:
    def test_finds_all_file_types(self, multi_type_dir):
        indexer = Indexer(multi_type_dir)
        files = indexer.find_files()
        suffixes = {f.suffix for f in files}
        assert ".py" in suffixes
        assert ".js" in suffixes
        assert ".md" in suffixes

    def test_build_indexes_all(self, multi_type_dir):
        indexer = Indexer(multi_type_dir)
        stats = indexer.build(verbose=False)
        assert stats["total_files"] == 3
        assert stats["indexed"] == 3
        assert stats["errors"] == 0

    def test_js_symbols_in_db(self, multi_indexed):
        _, db_path = multi_indexed
        results = query_js_files(db_path)
        names = [r["name"] for r in results]
        assert "DashboardManager" in names
        assert "initApp" in names

    def test_js_search_finds_symbols(self, multi_indexed):
        _, db_path = multi_indexed
        results = search_symbols(db_path, "%Dashboard%")
        names = [r["name"] for r in results]
        assert any("Dashboard" in n for n in names)

    def test_doc_sections_in_db(self, multi_indexed):
        _, db_path = multi_indexed
        results = query_doc_sections(db_path, "README.md")
        headings = [r["heading"] for r in results]
        assert "Project Overview" in headings
        assert "Installation" in headings

    def test_doc_fts_search(self, multi_indexed):
        _, db_path = multi_indexed
        results = query_docs(db_path, "quickast")
        assert len(results) >= 1

    def test_doc_search_in_headings(self, multi_indexed):
        _, db_path = multi_indexed
        results = search_symbols(db_path, "%Installation%")
        names = [r["name"] for r in results]
        assert any("Installation" in n for n in names)

    def test_js_files_search_filter(self, multi_indexed):
        _, db_path = multi_indexed
        results = query_js_files(db_path, search="init")
        names = [r["name"] for r in results]
        assert "initApp" in names

    def test_js_files_classes_only(self, multi_indexed):
        _, db_path = multi_indexed
        results = query_js_files(db_path, classes_only=True)
        assert all(r["symbol_type"] == "class" for r in results)
        names = [r["name"] for r in results]
        assert "DashboardManager" in names


class TestCallbackQueries:
    @pytest.fixture
    def callback_indexed(self, tmp_path):
        (tmp_path / "bot.py").write_text(SAMPLE_CALLBACKS)
        indexer = Indexer(tmp_path)
        indexer.build(verbose=False)
        return tmp_path, indexer.db_path

    def test_query_callbacks(self, callback_indexed):
        _, db_path = callback_indexed
        results = query_callbacks(db_path)
        cb_names = [r["callee_name"] for r in results]
        assert "handle_message" in cb_names
        assert "handle_error" in cb_names
        assert "button_handler" in cb_names

    def test_callback_has_caller(self, callback_indexed):
        _, db_path = callback_indexed
        results = query_callbacks(db_path)
        for r in results:
            assert r["caller_qualified"] is not None
            assert r["callee_object"] is not None
