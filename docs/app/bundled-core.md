# Bundled core: layout, environment and scan boundary

How the tray app ships and runs the Python core. The Rust side is `app/src-tauri/src/scan.rs`;
the rules behind it are in `app/src-tauri/AGENTS.md` and ADR-0006/0008.

## What is bundled

`bundle.resources` in `app/src-tauri/tauri.conf.json` copies the core project into the app's
resource folder under `core/`:

| Installed path | From |
|---|---|
| `core/pyproject.toml` | `core/pyproject.toml` |
| `core/uv.lock` | `core/uv.lock` (the frozen dependency set) |
| `core/.python-version` | `core/.python-version` |
| `core/README.md` | `core/README.md` (the build backend needs the `readme` the metadata names) |
| `core/src/` | `core/src/` (the package and its built-in TOML definitions) |

Tests, dev tools and the checkout's `.venv` are not bundled. `tauri dev` and `cargo build`
copy the same files next to the debug executable, so development runs the same layout.

## Where things are written

Nothing is written to the install folder.

| What | Where (Windows) |
|---|---|
| The core's virtual environment | `%LOCALAPPDATA%\io.github.7ahery.versionbar\core-env` (Tauri's `app_local_data_dir()`, local rather than roaming because it is large and machine specific) |
| Python bytecode for the bundled sources | `core-env\pycache` (`PYTHONPYCACHEPREFIX`), instead of `__pycache__` next to the sources |
| The managed Python and package downloads | uv's own folders (uv's cache and managed-Python directory), as for any uv project |

The environment survives app updates. After an update uv re-syncs it against the new
`uv.lock` on the next scan.

## The one invocation

```
uv run --frozen --no-dev --managed-python --project <resources>\core -- versionbar list --json
```

with `UV_PROJECT_ENVIRONMENT=<core-env>` and `PYTHONPYCACHEPREFIX=<core-env>\pycache` set and
`VIRTUAL_ENV` removed. The arguments are fixed; the webview cannot change them.

- `--frozen` installs exactly the bundled lock file and never rewrites it.
- `--no-dev` leaves out the contributor tools (pytest, ruff, ty).
- `--managed-python` uses a uv-managed Python only, never the system Python the core reports
  on. uv downloads one on first use if needed.

On the first run uv creates the environment, which can need a Python download. VersionBar
installs nothing itself, but this run makes uv download and install VersionBar's own Python
and dependencies into the folders above. Ticket 22 adds the setup screen and the 180-second
first-run timeout; until then every scan uses the 30-second timeout.

## Finding uv

Looked up again for every scan, in this order, taking the first `uv.exe` that is a file:

1. Each absolute entry of `PATH`.
2. `UV_INSTALL_DIR` (uv's installer puts the binary directly in that folder).
3. `%USERPROFILE%\.local\bin`, the installer's default, for an app started at login without
   the shell's `PATH`.

If none exists the outcome is `uv_missing` and nothing runs. VersionBar never installs uv.

## What the shell checks

The scan fails (`kind: "failed"`) with one of these reasons, and keeps the last good results:

| Reason | When |
|---|---|
| `launch` | uv could not be started. |
| `timeout` | No exit within the timeout. uv and everything it started are killed (`taskkill /F /T`). |
| `exit` | Nonzero exit code. stderr is attached. |
| `malformed` | stdout is not a JSON object. |
| `incompatible` | A JSON object whose `schema_version` is missing or not the one this build supports (`SUPPORTED_SCHEMA_VERSION`, checked against `schema/output.schema.json` by `tests/schema_version.rs`). |

Beyond that check the result is stored and passed on as the exact text the core printed.

## IPC contract with the popup

| Name | Kind | Payload |
|---|---|---|
| `get_state` | command | returns the state below |
| `refresh` | command | no arguments, returns nothing; starts a scan unless one is running |
| `scan-updated` | event, Rust to webview | the state below, sent when a scan starts and when it ends |

```ts
{
  scanning: boolean;
  current: ScanResult | null;   // latest successful scan, as printed by the core
  previous: ScanResult | null;  // the successful scan before it
  outcome: null                 // nothing has finished yet
    | { kind: "ok" }
    | { kind: "uv_missing" }
    | { kind: "failed"; reason: string; message: string; stderr: string };
}
```

The TS mirror is `app/src/shell.ts`. Consumers must handle unknown `kind` and `reason` values
(ticket 22 adds a setup state). State is held in memory only; ticket 24 saves it to disk.
