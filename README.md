# QuickAST

**Instant codebase intelligence for AI coding agents.**

QuickAST scans your Python codebase, builds a lightweight SQLite index of every symbol, call relationship, import, and API route, then keeps it current with automatic file watching. AI coding agents go from slow, token-burning exploratory searches to millisecond lookups.

One command to install. One command to index. Immediate speed improvements on every AI interaction.

## The Problem

AI coding agents (Claude Code, Cursor, Copilot, etc.) spend significant time searching your codebase using grep, file globbing, and exploratory reads. On large codebases, this:

- **Burns tokens** on search results that aren't relevant
- **Takes 30-75 seconds** per exploratory search
- **Misses context** because agents can only search linearly
- **Bloats the context window** with raw grep output

## The Solution

QuickAST pre-indexes your entire codebase into a queryable SQLite database. When an AI agent needs to find a symbol, trace a call chain, or understand module architecture, it gets the answer in **milliseconds** instead of minutes.

```
# Before QuickAST: Agent greps blindly
$ rg "def create_user" --type py     # 30+ seconds on large repos, noisy results

# After QuickAST: Precise, instant answers
$ quickast query create_user         # <1ms, exact definition with file + line
$ quickast callers-of create_user    # <1ms, every call site across the codebase
$ quickast callees create_user       # <1ms, everything this function calls
```

## Quick Start

### Install

```bash
pip install quickast
```

### Index your project

```bash
cd /path/to/your/project
quickast init
```

That's it. QuickAST walks your project, parses every Python file using AST analysis, and builds the index. For a 100-file project, this takes about 2 seconds.

### Start the file watcher (optional)

```bash
quickast watch
```

This runs in the background and automatically re-indexes any file you save. The index stays perfectly current without manual rebuilds.

## Commands

| Command | What It Does |
|---------|-------------|
| `quickast init` | Build the index for the current project |
| `quickast watch` | Start the file watcher daemon |
| `quickast query <name>` | Find where a symbol (function/class/method) is defined |
| `quickast search <pattern>` | Fuzzy search symbols (use `%` wildcards: `%user%`, `%auth%`) |
| `quickast refs <name>` | Find all files that import a symbol |
| `quickast file <path>` | List all symbols defined in a file |
| `quickast callees <name>` | What does function X call? |
| `quickast callers-of <name>` | What calls function X? |
| `quickast impact <name> [depth]` | Transitive impact analysis (upstream + downstream) |
| `quickast routes [--type TYPE]` | List API routes (REST, CLI commands, pages) |
| `quickast route <path>` | Find a specific route handler |
| `quickast changes [hours]` | Files changed recently (default: 24 hours) |
| `quickast summary <path>` | Module overview (symbol counts, top definitions) |
| `quickast stats` | Index statistics |

## What Gets Indexed

QuickAST extracts and indexes:

- **Symbols** — Every function, class, and method with full signatures, docstrings, and line numbers
- **Call graph** — Every function call with caller/callee context, enabling "who calls X?" and "what does X call?" queries
- **Imports** — Every import statement, enabling "which files use module X?" queries
- **API routes** — FastAPI, Flask, and Click decorator patterns automatically detected
- **File metadata** — Line counts, modification times, and file sizes for change tracking

## How QuickAST Compares

|  | tree-sitter | ast-grep | symbex | **QuickAST** |
|--|-------------|----------|--------|------------|
| Persistent SQLite index | - | - | - | **Yes** |
| Call graph (callers/callees) | - | - | - | **Yes** |
| Transitive impact analysis | - | - | - | **Yes** |
| API route map | - | - | - | **Yes** |
| Live file watching | - | - | - | **Yes** |
| AI agent integration | - | - | - | **Yes** |
| Millisecond queries | - | - | - | **Yes** |
| Symbol search | - | Pattern-based | Yes | **Yes** |
| Multi-framework detection | - | - | - | **Yes** |

**tree-sitter** is a low-level parsing library. It gives you AST nodes but no index, no persistence, no call graph. You'd have to build everything on top of it.

**ast-grep** is a pattern matching tool for one-off searches. No persistent index — every query re-parses from scratch. No call graph or route detection.

**symbex** finds Python symbols and prints source code. Stateless — no index, no call graph, no callers/callees, no file watching. Re-parses the codebase on every invocation.

## Using QuickAST with AI Agents

### With Claude Code

Add this to your project's `CLAUDE.md`:

```markdown
## Code Index

This project has a QuickAST index. Query it before grepping:

\`\`\`bash
quickast query <name>         # Find symbol definitions
quickast search %keyword%     # Fuzzy search
quickast callers-of <name>    # Who calls this?
quickast callees <name>       # What does this call?
quickast file <path>          # What's in this file?
quickast impact <name>        # Full dependency chain
quickast routes               # API surface map
\`\`\`

Always query the index first. Only fall back to grep for string literals,
comments, or config values that aren't in the AST.
\`\`\`
```

### With Other AI Tools

QuickAST is a standard CLI tool. Any AI agent that can run shell commands can use it. Point the agent to the commands above and it will start using the index automatically.

## How It Works

1. **Parse** — QuickAST uses Python's built-in `ast` module to parse every `.py` file into an Abstract Syntax Tree
2. **Extract** — Symbols, imports, call relationships, and route decorators are extracted from the AST
3. **Store** — Everything goes into a SQLite database (`.quickast.db`) in your project root
4. **Watch** — The optional file watcher uses `watchdog` to detect changes and re-index only modified files
5. **Query** — The CLI reads from SQLite, which returns results in under 1ms for most queries

The index is a single `.quickast.db` file. Add it to your `.gitignore` — it's generated and can be rebuilt in seconds.

## Configuration

QuickAST automatically excludes common non-source directories:

- `venv`, `.venv`, `env`, `.env`
- `__pycache__`, `.git`, `node_modules`
- `.mypy_cache`, `.pytest_cache`, `.tox`, `.nox`
- `dist`, `build`, `.eggs`

## Requirements

- **Python**: 3.10+
- **OS**: Linux, macOS (Windows support planned)
- **Dependencies**: `watchdog` (for file watching only)

No external parsing libraries needed — QuickAST uses Python's built-in `ast` module.

## License

MIT

## Contributing

Contributions welcome. Please open an issue first to discuss what you'd like to change.
