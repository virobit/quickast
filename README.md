# QuickAST

**AST-powered codebase index for Python projects.**

QuickAST parses your Python codebase, builds a SQLite index of every symbol, call relationship, import, and API route, then keeps it current with automatic file watching.

## Installation

```bash
pip install quickast
```

Then navigate to any Python project and build the index:

```bash
cd /path/to/your/project
quickast init
```

### Install from source (alternative)

```bash
git clone https://github.com/virobit/quickast.git
cd quickast
pip install -e .
```

Editable mode (`-e`) means changes to the cloned source take effect immediately without reinstalling.

### Upgrading

```bash
pip install --upgrade quickast
```

Or if installed from source:

```bash
cd quickast
git pull
```

## What It Does

QuickAST gives you a persistent, queryable index of your codebase:

```bash
$ quickast query create_user           # Find where a symbol is defined
  function  app/users.py:45  def create_user(name: str, email: str) -> dict

$ quickast callers-of create_user      # What calls this function?
  app/api.py:112  in handle_signup
  tests/test_users.py:23  in test_create

$ quickast callees create_user         # What does this function call?
  L46  validate_email (method)
  L48  save_record (method)

$ quickast impact create_user          # Transitive dependency chain
  Upstream callers (3): handle_signup, register_endpoint, ...
  Downstream callees (5): validate_email, save_record, ...
```

Queries return in milliseconds from the SQLite index. No re-parsing, no scanning.

## Quick Start

### Start the file watcher (optional)

```bash
quickast watch           # Foreground (see output, Ctrl+C to stop)
quickast watch --daemon  # Background (frees your terminal)
quickast stop            # Stop the background watcher
```

Check if the watcher is running:

```bash
cat .quickast.pid        # Show the watcher's process ID
ps -p $(cat .quickast.pid) -o pid,cmd   # Verify the process is alive
```

Re-indexes any file you save. The index stays current without manual rebuilds.

## Commands

| Command | What It Does |
|---------|-------------|
| `quickast init` | Build the index for the current project |
| `quickast watch [--daemon]` | Start the file watcher (`--daemon` to run in background) |
| `quickast stop` | Stop the background watcher |
| `quickast query <name>` | Find where a symbol (function/class/method) is defined |
| `quickast search <pattern>` | Search symbols (use `%` wildcards: `%user%`, `%auth%`) |
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

- **Symbols** — Every function, class, and method with full signatures, docstrings, and line numbers
- **Call graph** — Every function call with caller/callee context (who calls X, what does X call)
- **Imports** — Every import statement (which files use module X)
- **API routes** — FastAPI, Flask, and Click decorator patterns
- **File metadata** — Line counts, modification times, file sizes

## Capabilities

| Feature | Description |
|---------|-------------|
| Persistent SQLite index | Index once, query instantly — no re-parsing on each lookup |
| Call graph | Trace callers and callees across the entire codebase |
| Transitive impact analysis | See the full upstream/downstream dependency chain at any depth |
| API route map | Automatically detects REST endpoints, CLI commands, and page routes |
| Live file watching | File watcher re-indexes on save — index stays current |
| Incremental indexing | Only re-indexes files that changed since the last build |
| Framework detection | Recognizes FastAPI, Flask, and Click patterns out of the box |

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
```

### With Other AI Tools

QuickAST is a standard CLI tool. Any AI agent that can run shell commands can use it.

## How It Works

1. **Parse** — Uses Python's built-in `ast` module to parse every `.py` file
2. **Extract** — Pulls symbols, imports, call relationships, and route decorators from the AST
3. **Store** — Writes everything to a SQLite database (`.quickast.db`) in your project root
4. **Watch** — The file watcher uses `watchdog` to detect changes and re-index modified files
5. **Query** — The CLI reads from SQLite, returning results in under 1ms

The index is a single `.quickast.db` file. Add it to `.gitignore` — it can be rebuilt in seconds.

## Configuration

QuickAST automatically excludes common non-source directories:

- `venv`, `.venv`, `env`, `.env`
- `__pycache__`, `.git`, `node_modules`
- `.mypy_cache`, `.pytest_cache`, `.tox`, `.nox`
- `dist`, `build`, `.eggs`

## Requirements

- **Python**: 3.10+
- **OS**: Linux, macOS
- **Dependencies**: `watchdog` (for file watching)

No external parsing libraries — QuickAST uses Python's built-in `ast` module.

## License

MIT

## Running Tests

Tests are in the cloned repo, not in the pip install. You must run them from inside the `quickast` directory.

```bash
git clone https://github.com/virobit/quickast.git
cd quickast
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"    # Installs pytest and pytest-cov
pytest tests/ -v           # Run from inside the quickast directory
```

All 24 tests should pass. The tests cover parsing, indexing, incremental builds, and all query types using temporary project directories — no external dependencies or network access required.

## Contributing

Contributions welcome. Please open an issue first to discuss what you'd like to change.

## Disclaimer

QuickAST is provided "as is", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement. In no event shall the authors or copyright holders be liable for any claim, damages, or other liability, whether in an action of contract, tort, or otherwise, arising from, out of, or in connection with the software or the use or other dealings in the software.

QuickAST performs read-only analysis of your source code using Python's built-in `ast` module. It does not modify, execute, or transmit your code. The SQLite index is stored locally in your project directory.

This project is in early development. APIs and CLI behavior may change between versions.
