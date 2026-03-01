"""AST parsing for Python files — extracts symbols, imports, calls, and routes."""

import ast
import re
import json
from pathlib import Path


def parse_file(filepath: Path) -> dict:
    """Parse a Python file and extract all indexable information."""
    result = {
        "symbols": [],
        "imports": [],
        "calls": [],
        "routes": [],
        "line_count": 0,
    }

    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return result

    result["line_count"] = source.count("\n") + 1

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return result

    _extract_symbols(tree, result["symbols"], parent=None, parent_name=None)
    _extract_imports(tree, result["imports"])
    _extract_calls(tree, result["calls"])
    _extract_routes(tree, result["routes"])

    return result


# ── Symbol extraction ────────────────────────────────────────────────


def _get_signature(node) -> str:
    """Build a human-readable signature for a function/method node."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return ""
    args = []
    all_args = node.args
    defaults_offset = len(all_args.args) - len(all_args.defaults)
    for i, arg in enumerate(all_args.args):
        a = arg.arg
        if arg.annotation and hasattr(ast, "unparse"):
            try:
                a += f": {ast.unparse(arg.annotation)}"
            except Exception:
                pass
        default_idx = i - defaults_offset
        if 0 <= default_idx < len(all_args.defaults):
            try:
                a += f"={ast.unparse(all_args.defaults[default_idx])}"
            except Exception:
                a += "=..."
        args.append(a)
    if all_args.vararg:
        args.append(f"*{all_args.vararg.arg}")
    for i, arg in enumerate(all_args.kwonlyargs):
        a = arg.arg
        if i < len(all_args.kw_defaults) and all_args.kw_defaults[i] is not None:
            try:
                a += f"={ast.unparse(all_args.kw_defaults[i])}"
            except Exception:
                a += "=..."
        args.append(a)
    if all_args.kwarg:
        args.append(f"**{all_args.kwarg.arg}")
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = ""
    if node.returns and hasattr(ast, "unparse"):
        try:
            ret = f" -> {ast.unparse(node.returns)}"
        except Exception:
            pass
    return f"{prefix} {node.name}({', '.join(args)}){ret}"


def _get_docstring(node) -> str | None:
    """Extract the first line of a node's docstring."""
    try:
        ds = ast.get_docstring(node)
        if ds:
            return ds.split("\n")[0].strip()[:200]
    except Exception:
        pass
    return None


def _extract_symbols(node, symbols: list, parent=None, parent_name=None):
    """Recursively extract class and function symbols from the AST."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            qualified = f"{parent_name}.{child.name}" if parent_name else child.name
            sig = f"class {child.name}"
            if child.bases:
                try:
                    bases = ", ".join(ast.unparse(b) for b in child.bases)
                    sig = f"class {child.name}({bases})"
                except Exception:
                    pass
            sym = {
                "name": child.name, "qualified_name": qualified, "type": "class",
                "line": child.lineno, "end_line": getattr(child, "end_lineno", None),
                "signature": sig, "docstring": _get_docstring(child), "children": [],
            }
            symbols.append(sym)
            _extract_symbols(child, sym["children"], parent=child, parent_name=qualified)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sym_type = "method" if parent and isinstance(parent, ast.ClassDef) else "function"
            qualified = f"{parent_name}.{child.name}" if parent_name else child.name
            sym = {
                "name": child.name, "qualified_name": qualified, "type": sym_type,
                "line": child.lineno, "end_line": getattr(child, "end_lineno", None),
                "signature": _get_signature(child), "docstring": _get_docstring(child),
                "children": [],
            }
            symbols.append(sym)


# ── Import extraction ────────────────────────────────────────────────


def _extract_imports(tree, imports: list):
    """Extract all import statements from the AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({
                    "module": alias.name, "name": None,
                    "alias": alias.asname, "line": node.lineno,
                })
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append({
                    "module": module, "name": alias.name,
                    "alias": alias.asname, "line": node.lineno,
                })


# ── Call graph extraction ────────────────────────────────────────────


class _CallVisitor(ast.NodeVisitor):
    """Walk the AST tracking scope and collecting function/method calls."""

    def __init__(self):
        self.calls: list[dict] = []
        self._scope_stack: list[str] = []

    def _current_scope(self) -> str:
        return ".".join(self._scope_stack) if self._scope_stack else "<module>"

    def visit_ClassDef(self, node):
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node):
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        caller = self._current_scope()
        func = node.func

        if isinstance(func, ast.Name):
            self.calls.append({
                "caller": caller, "callee_name": func.id,
                "callee_type": "direct", "callee_object": None,
                "line": node.lineno,
            })
        elif isinstance(func, ast.Attribute):
            obj_name = self._resolve_object(func.value)
            if obj_name in ("self", "cls"):
                ctype = "method"
            else:
                ctype = "attribute"
            # Detect set_*_callback() wiring pattern
            if (func.attr.startswith("set_") and func.attr.endswith("_callback")
                    and node.args):
                arg = node.args[0]
                cb_name = getattr(arg, "id", None) if isinstance(arg, ast.Name) else None
                if cb_name:
                    self.calls.append({
                        "caller": caller, "callee_name": cb_name,
                        "callee_type": "callback_wire",
                        "callee_object": f"{obj_name}.{func.attr}",
                        "line": node.lineno,
                    })
            self.calls.append({
                "caller": caller, "callee_name": func.attr,
                "callee_type": ctype, "callee_object": obj_name,
                "line": node.lineno,
            })


        # Detect on_* keyword args as callback wiring
        for kw in node.keywords:
            if (kw.arg and kw.arg.startswith("on_")
                    and isinstance(kw.value, ast.Name)):
                self.calls.append({
                    "caller": caller, "callee_name": kw.value.id,
                    "callee_type": "callback_wire",
                    "callee_object": f"kwarg:{kw.arg}",
                    "line": node.lineno,
                })

        self.generic_visit(node)

    def _resolve_object(self, node, depth=0) -> str:
        if depth > 3:
            return "?"
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = self._resolve_object(node.value, depth + 1)
            return f"{parent}.{node.attr}"
        if isinstance(node, ast.Call):
            return self._resolve_object(node.func, depth + 1) + "()"
        return "?"


def _extract_calls(tree, calls: list):
    """Extract all function/method calls with caller context."""
    visitor = _CallVisitor()
    visitor.visit(tree)
    calls.extend(visitor.calls)


# ── Route extraction ─────────────────────────────────────────────────

# Supported HTTP methods for framework detection
_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "websocket", "head", "options"}

# Common router variable names across frameworks
_ROUTER_NAMES = {"app", "router", "api", "blueprint", "bp"}


def _extract_routes(tree, routes: list):
    """Extract API routes from decorator patterns (FastAPI, Flask, etc.)."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for deco in node.decorator_list:
            # REST routes: @app.get("/path") or @router.post("/path")
            if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute):
                attr = deco.func.attr
                if attr in _HTTP_METHODS:
                    obj = deco.func.value
                    obj_name = getattr(obj, "id", None) if isinstance(obj, ast.Name) else None
                    if obj_name and (obj_name in _ROUTER_NAMES or obj_name.endswith("_router")):
                        path = ""
                        if deco.args and isinstance(deco.args[0], ast.Constant):
                            path = str(deco.args[0].value)
                        is_page = any(
                            isinstance(kw.value, ast.Name) and kw.value.id == "HTMLResponse"
                            for kw in deco.keywords
                            if kw.arg == "response_class"
                        )
                        routes.append({
                            "route_type": "page" if is_page else "rest",
                            "path": path, "method": attr.upper(),
                            "handler": node.name, "qualified": None,
                            "line": node.lineno,
                            "description": _get_docstring(node),
                            "extra": None,
                        })

            # Flask-style: @app.route("/path", methods=["GET"])
            if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute):
                if deco.func.attr == "route":
                    obj = deco.func.value
                    obj_name = getattr(obj, "id", None) if isinstance(obj, ast.Name) else None
                    if obj_name and (obj_name in _ROUTER_NAMES or obj_name.endswith("_bp")):
                        path = ""
                        if deco.args and isinstance(deco.args[0], ast.Constant):
                            path = str(deco.args[0].value)
                        methods = ["GET"]
                        for kw in deco.keywords:
                            if kw.arg == "methods" and isinstance(kw.value, ast.List):
                                methods = [
                                    e.value for e in kw.value.elts
                                    if isinstance(e, ast.Constant)
                                ]
                        routes.append({
                            "route_type": "rest",
                            "path": path, "method": ",".join(methods),
                            "handler": node.name, "qualified": None,
                            "line": node.lineno,
                            "description": _get_docstring(node),
                            "extra": None,
                        })

            # Django-style URLs are defined in urlpatterns, not decorators.
            # Click CLI commands: @cli.command() or @app.cli.command()
            if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute):
                if deco.func.attr == "command":
                    cmd_name = node.name.replace("_", "-")
                    for kw in deco.keywords:
                        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                            cmd_name = str(kw.value.value)
                    if deco.args and isinstance(deco.args[0], ast.Constant):
                        cmd_name = str(deco.args[0].value)
                    routes.append({
                        "route_type": "cli_command",
                        "path": cmd_name, "method": None,
                        "handler": node.name, "qualified": None,
                        "line": node.lineno,
                        "description": _get_docstring(node),
                        "extra": None,
                    })

    # Router mount tracking: app.include_router(router_name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "include_router"):
            continue
        obj = node.func.value
        app_name = getattr(obj, "id", "?") if isinstance(obj, ast.Name) else "?"
        router_arg = node.args[0] if node.args else None
        router_name = getattr(router_arg, "id", "?") if isinstance(router_arg, ast.Name) else "?"
        prefix = ""
        for kw in node.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                prefix = kw.value.value
        routes.append({
            "route_type": "router_mount",
            "path": prefix or "(mounted)",
            "method": "INCLUDE_ROUTER",
            "handler": router_name,
            "qualified": f"{app_name}.include_router({router_name})",
            "line": node.lineno,
            "description": f"Router {router_name} mounted on {app_name}",
            "extra": json.dumps({"app": app_name, "router": router_name, "prefix": prefix}),
        })


# ── JS/MD Parsing ───────────────────────────────────────────────────

_JS_PATTERNS = [
    (re.compile(r'(?:async\s+)?function\s+(\w+)\s*\('), "function"),
    (re.compile(r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[a-zA-Z_]\w*)\s*=>'), "arrow_function"),
    (re.compile(r'setInterval\s*\('), "setInterval"),
    (re.compile(r'setTimeout\s*\('), "setTimeout"),
]
_INTERVAL_RE = re.compile(r',\s*(\d+)\s*\)')

_JS_CLASS_RE = re.compile(r'^\s*class\s+(\w+)')
_JS_METHOD_RE = re.compile(r'^\s+(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*\{')
_JS_NOT_METHODS = frozenset({"if", "else", "for", "while", "switch", "catch", "return", "new", "typeof", "delete", "void", "throw"})
_JS_GETTER_RE = re.compile(r'^\s+get\s+(\w+)\s*\(\)')
_JS_STATIC_RE = re.compile(r'^(\w+)\.(\w+)\s*=\s*function')

def parse_js_file(filepath: Path) -> dict:
    result = {"js_symbols": [], "line_count": 0}
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return result

    lines = source.split("\n")
    result["line_count"] = len(lines)

    current_class = None
    brace_depth = 0
    class_start_depth = 0

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        brace_depth += stripped.count("{") - stripped.count("}")

        m = _JS_CLASS_RE.match(line)
        if m:
            current_class = m.group(1)
            class_start_depth = brace_depth
            result["js_symbols"].append({
                "name": current_class, "symbol_type": "class",
                "line": line_num, "end_line": None, "params": None,
                "interval_ms": None, "parent_class": None,
            })
            continue

        if current_class and brace_depth < class_start_depth:
            current_class = None

        if current_class:
            m = _JS_GETTER_RE.match(line)
            if m:
                result["js_symbols"].append({
                    "name": m.group(1), "symbol_type": "getter",
                    "line": line_num, "end_line": None, "params": None,
                    "interval_ms": None, "parent_class": current_class,
                })
                continue

        if current_class:
            m = _JS_METHOD_RE.match(line)
            if m and m.group(1) not in _JS_NOT_METHODS:
                result["js_symbols"].append({
                    "name": m.group(1), "symbol_type": "method",
                    "line": line_num, "end_line": None, "params": m.group(2).strip(),
                    "interval_ms": None, "parent_class": current_class,
                })
                continue

        m = _JS_STATIC_RE.match(stripped)
        if m:
            result["js_symbols"].append({
                "name": m.group(2), "symbol_type": "static_method",
                "line": line_num, "end_line": None, "params": None,
                "interval_ms": None, "parent_class": m.group(1),
            })
            continue

        if not current_class:
            for pattern, sym_type in _JS_PATTERNS:
                pm = pattern.search(line)
                if not pm:
                    continue
                if sym_type in ("setInterval", "setTimeout"):
                    interval_ms = None
                    search_text = "\n".join(lines[line_num - 1:line_num + 4])
                    iv = _INTERVAL_RE.search(search_text)
                    if iv:
                        try:
                            interval_ms = int(iv.group(1))
                        except ValueError:
                            pass
                    result["js_symbols"].append({
                        "name": sym_type, "symbol_type": sym_type,
                        "line": line_num, "end_line": None, "params": None,
                        "interval_ms": interval_ms, "parent_class": None,
                    })
                else:
                    name = pm.group(1) if pm.lastindex and pm.group(1) else f"anon_{line_num}"
                    result["js_symbols"].append({
                        "name": name, "symbol_type": sym_type,
                        "line": line_num, "end_line": None, "params": None,
                        "interval_ms": None, "parent_class": None,
                    })
                break

    return result

_HEADING_RE = re.compile(r'^(#{1,4})\s+(.+)')

def parse_markdown_file(filepath: Path) -> dict:
    result = {"sections": [], "fts_entries": [], "line_count": 0}
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return result

    lines = source.split("\n")
    result["line_count"] = len(lines)

    rel_path = str(filepath)
    headings = []
    for line_num, line in enumerate(lines, 1):
        m = _HEADING_RE.match(line)
        if m:
            headings.append({
                "heading": m.group(2).strip(),
                "level": len(m.group(1)),
                "line": line_num,
                "end_line": None,
                "parent_idx": None,
            })

    for i, h in enumerate(headings):
        if i + 1 < len(headings):
            h["end_line"] = headings[i + 1]["line"] - 1
        else:
            h["end_line"] = len(lines)

    parent_stack = []
    for i, h in enumerate(headings):
        while parent_stack and parent_stack[-1][0] >= h["level"]:
            parent_stack.pop()
        if parent_stack:
            h["parent_idx"] = parent_stack[-1][1]
        parent_stack.append((h["level"], i))

    result["sections"] = headings

    for h in headings:
        start = h["line"]
        end = h["end_line"]
        content = "\n".join(lines[start - 1:end])
        result["fts_entries"].append({
            "file_path": rel_path,
            "heading": h["heading"],
            "content": content,
        })

    if not headings and source.strip():
        result["fts_entries"].append({
            "file_path": rel_path,
            "heading": filepath.stem,
            "content": source[:10000],
        })

    return result
