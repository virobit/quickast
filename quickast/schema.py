"""Database schema for QuickAST index."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    relative_path TEXT NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    line_count INTEGER DEFAULT 0,
    indexed_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    qualified_name TEXT,
    type TEXT NOT NULL,
    line INTEGER NOT NULL,
    end_line INTEGER,
    signature TEXT,
    docstring TEXT,
    parent_id INTEGER REFERENCES symbols(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    module TEXT NOT NULL,
    name TEXT,
    alias TEXT,
    line INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS call_references (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    caller_qualified TEXT NOT NULL,
    callee_name TEXT NOT NULL,
    callee_type TEXT NOT NULL,
    callee_object TEXT,
    line INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS api_routes (
    id INTEGER PRIMARY KEY,
    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    route_type TEXT NOT NULL,
    path TEXT NOT NULL,
    method TEXT,
    handler_function TEXT,
    handler_qualified TEXT,
    line INTEGER NOT NULL,
    description TEXT,
    service TEXT,
    extra TEXT
);

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_symbols_type ON symbols(type);
CREATE INDEX IF NOT EXISTS idx_symbols_qualified ON symbols(qualified_name);
CREATE INDEX IF NOT EXISTS idx_imports_name ON imports(name);
CREATE INDEX IF NOT EXISTS idx_imports_module ON imports(module);
CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
CREATE INDEX IF NOT EXISTS idx_files_relative ON files(relative_path);
CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime);
CREATE INDEX IF NOT EXISTS idx_calls_caller ON call_references(caller_qualified);
CREATE INDEX IF NOT EXISTS idx_calls_callee ON call_references(callee_name);
CREATE INDEX IF NOT EXISTS idx_calls_file ON call_references(file_id);
CREATE INDEX IF NOT EXISTS idx_calls_callee_obj ON call_references(callee_object, callee_name);
CREATE INDEX IF NOT EXISTS idx_api_path ON api_routes(path);
CREATE INDEX IF NOT EXISTS idx_api_type ON api_routes(route_type);
CREATE INDEX IF NOT EXISTS idx_api_handler ON api_routes(handler_function);
CREATE INDEX IF NOT EXISTS idx_api_file ON api_routes(file_id);

CREATE TABLE IF NOT EXISTS js_file_symbols (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    symbol_type TEXT NOT NULL,
    line INTEGER NOT NULL,
    end_line INTEGER,
    params TEXT,
    interval_ms INTEGER,
    parent_class TEXT
);

CREATE TABLE IF NOT EXISTS doc_sections (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    heading TEXT NOT NULL,
    level INTEGER NOT NULL,
    line INTEGER NOT NULL,
    end_line INTEGER,
    parent_id INTEGER REFERENCES doc_sections(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(
    file_path,
    heading,
    content,
    tokenize='porter unicode61'
);

CREATE INDEX IF NOT EXISTS idx_jsf_name ON js_file_symbols(name);
CREATE INDEX IF NOT EXISTS idx_jsf_file ON js_file_symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_jsf_type ON js_file_symbols(symbol_type);
CREATE INDEX IF NOT EXISTS idx_doc_file ON doc_sections(file_id);
"""
