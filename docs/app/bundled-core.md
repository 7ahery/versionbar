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
| The app version the environment was last synced for | `core-env-version.txt`, next to `core-env` (not inside: uv owns that folder) |

The environment survives app updates. After an update uv re-syncs it against the new
`uv.lock` on the next scan, which therefore runs as a first run (below): the shell writes the
app version to `core-env-version.txt` after every successful scan and treats a different or
missing version as a first run ([updates.md](updates.md#installing)).

## The two invocations

```
uv run --frozen --no-dev --managed-python --project <resources>\core -- versionbar list --json
uv run --frozen --no-dev --managed-python --project <resources>\core -- versionbar config --json
```

The first is the scan; the second is the preferences query (ADR 0011), described in
[preferences.md](preferences.md). Both run with `UV_PROJECT_ENVIRONMENT=<core-env>` and
`PYTHONPYCACHEPREFIX=<core-env>\pycache` set and `VIRTUAL_ENV` removed, and share everything
on this page: the uv lookup, the removed variables, the timeout and how a run is stopped. Each
scan job runs the query first and the scan straight after, never both at once. The arguments
are fixed (`Query` in `scan.rs`); the webview cannot change them.

### Inherited uv and Python settings

The app inherits the user's environment, and uv reads many settings from `UV_*` variables. The
ones that would change which project, Python, environment or dependency set this invocation
uses, or contradict its flags, are removed before uv starts (`OVERRIDDEN_UV_VARIABLES` in
`scan.rs`, checked against `uv run --help` for uv 0.12):

| Group | Removed |
|---|---|
| Which Python | `UV_PYTHON`, `UV_MANAGED_PYTHON`, `UV_NO_MANAGED_PYTHON`, `UV_SYSTEM_PYTHON`, `UV_PYTHON_PREFERENCE` |
| Which project and environment | `UV_PROJECT`, `UV_WORKING_DIR`, `UV_NO_PROJECT`, `UV_ISOLATED` (`UV_PROJECT_ENVIRONMENT` is set by the app) |
| How the environment is synced | `UV_LOCKED` (clashes with `--frozen`), `UV_FROZEN`, `UV_NO_SYNC`, `UV_NO_DEV`, `UV_NO_DEFAULT_GROUPS`, `UV_NO_GROUP`, `UV_NO_EDITABLE`, `UV_NO_SOURCES`, `UV_NO_SOURCES_PACKAGE` |
| Extra variables | `UV_ENV_FILE` (a dotenv file would load arbitrary variables into the core) |

Python reads a few variables of its own that would point the core's interpreter at another
standard library or other package folders, or run extra code in it. These are removed too
(`OVERRIDDEN_PYTHON_VARIABLES`): `PYTHONHOME`, `PYTHONPATH`, `PYTHONPLATLIBDIR`,
`PYTHONUSERBASE`, `PYTHONEXECUTABLE`, `PYTHONSTARTUP` and `PYTHONINSPECT`. Variables that only
tune behaviour (`PYTHONIOENCODING`, `PYTHONUTF8`, `PYTHONWARNINGS`, ...) are passed on; the
core sets its own output encoding.

Everything else is passed on, on purpose: index and mirror settings (`UV_INDEX_URL`,
`UV_DEFAULT_INDEX`, `UV_PYTHON_INSTALL_MIRROR`, ...), proxies and TLS (`HTTPS_PROXY`,
`UV_NATIVE_TLS`, ...), cache and install locations (`UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`),
and offline or download policy (`UV_OFFLINE`, `UV_PYTHON_DOWNLOADS`). A user behind a company
mirror or proxy needs them for the first-run download. uv config files (`uv.toml`) are read as
usual for the same reason; the command-line flags above take precedence over them.

The removed variables are also absent for the core and the tools it runs. Today the core only
runs `--version` commands, which ignore the `UV_*` ones; a future provider that asks uv itself
about Pythons would not see the user's `UV_PYTHON` and similar settings. The `PYTHON*` ones
do matter for one case: a user Python that only works with the user's `PYTHONHOME` (or breaks
because of it) is checked without it, so the scan reports it as it runs in a clean
environment.

- `--frozen` installs exactly the bundled lock file and never rewrites it.
- `--no-dev` leaves out the contributor tools (pytest, ruff, ty).
- `--managed-python` uses a uv-managed Python only, never the system Python the core reports
  on. uv downloads one on first use if needed.

On the first run uv creates the environment, which can need a Python download. VersionBar
installs nothing itself, but this run makes uv download and install VersionBar's own Python
and dependencies into the folders above. That run is the "first run": the shell decides it by
whether the environment folder (`core-env`) exists before it starts uv (and, after an app update,
by `core-env-version.txt`), and gives it a 180-second
timeout instead of 30 seconds. While it runs, the state says `setting_up: true`. The first-run
rules (180 seconds, `setting_up`) last until one scan succeeds, so a first run that timed out
after creating the folder is retried with the same allowance. The preferences query runs first
in each job and gets the same timeout, so on a first run it is usually the one that builds the
environment. What users can do about each failure is in
[../troubleshooting.md](../troubleshooting.md).

The 30-second limit is fixed and does not follow the config file: per-tool `timeout` or
`timeouts.<id>` values near or above about 30 seconds can make the whole scan time out (see
[preferences.md](preferences.md#timeouts-in-the-config-file) and
[../config.md](../config.md#keys)).

The timeout applies to each invocation separately, not to the job. On a first run the
preferences query and the scan each get 180 seconds, so if the query hangs until it is
stopped and the scan then runs as long as it may, `setting_up` can last about 6 minutes.

## Finding uv

Looked up again for every scan job (one lookup serves its preferences query and scan), in this
order, taking the first `uv.exe` that is a file:

1. Each entry of `PATH`.
2. `UV_INSTALL_DIR` (uv's installer puts the binary directly in that folder).
3. `%USERPROFILE%\.local\bin`, the installer's default, for an app started at login without
   the shell's `PATH`.

Relative or empty folders are skipped at every step: they would resolve against the app's
working directory, which nobody chose. The core treats `PATH` the same way.

If none exists the outcome is `uv_missing` and nothing runs. VersionBar never installs uv.

## What the shell checks

The scan fails (`kind: "failed"`) with one of these reasons, and keeps the last good results.
The preferences query uses the same reasons, except that exit code 3 with a valid answer is
not a failure ([preferences.md](preferences.md#how-each-ending-is-handled)).

| Reason | When |
|---|---|
| `launch` | uv could not be started. |
| `timeout` | No exit within the timeout. uv and everything it started are killed (`taskkill /F /T`, given at most one second like the core's own; then uv itself is killed directly). |
| `exit` | Nonzero exit code (stderr is attached), or the operating system could not report whether uv was still running; uv is then stopped like a timed-out scan and the message carries the error. |
| `malformed` | stdout is not a JSON object. |
| `incompatible` | A JSON object whose `schema_version` is missing or not the one this build supports (`SUPPORTED_SCHEMA_VERSION`, checked against `schema/output.schema.json` by `tests/schema_version.rs`). |

Beyond that check the result is stored and passed on as the exact text the core printed.

### Output after an exit or a kill

stdout and stderr are read on background threads. Once uv has exited (or been killed) the
shell waits at most one second more for the pipes to close, then goes on with what arrived. A
process outside the killed tree that inherited the pipes can keep them open; its reader thread
is then left behind until the pipe closes, because a blocked read cannot be cancelled. This is
accepted: it holds a few kilobytes of memory, never delays a scan by more than that second, and
matches what the core does for the tools it runs (`_DRAIN_SECONDS` in
`core/src/versionbar/system/real.py`).

## IPC contract with the popup

| Name | Kind | Payload |
|---|---|---|
| `get_state` | command | returns the state below |
| `get_preferences` | command | no arguments; returns the preferences state ([preferences.md](preferences.md#ipc-contract-with-the-popup)) |
| `refresh` | command | no arguments, returns nothing; starts a scan, or, while one is running, one more scan after it ([state.md](state.md#when-it-refreshes)) |
| `open_uv_docs` | command | no arguments, returns nothing; opens the official uv installation guide in the default browser (the address is fixed in Rust) |
| `open_containing_folder` | command | `{ path: string }`; opens Explorer on the folder holding that file, with it selected. Rejects with a sentence for the user when the path is refused or Explorer cannot start ([actions.md](actions.md)) |
| `scan-updated` | event, Rust to webview | the state below, sent when a scan starts and when it ends |
| `preferences-updated` | event, Rust to webview | the preferences state, sent after every preferences query ([preferences.md](preferences.md)) |
| `get_update`, `install_update`, `update-updated` | commands and event | the app update on offer and the user's confirmation ([updates.md](updates.md#ipc-contract-with-the-popup)) |

```ts
{
  scanning: boolean;
  setting_up: boolean;          // true only while a first run (no core-env yet, or the first
                                // scan after an app update) is scanning
  current: ScanResult | null;   // latest successful scan, as printed by the core
  previous: ScanResult | null;  // the successful scan before it
  outcome: null                 // nothing has finished in this session yet (current and
                                // previous may still hold results restored from disk)
    | { kind: "ok" }
    | { kind: "uv_missing" }
    | { kind: "failed"; reason: string; message: string; stderr: string };
}
```

A consumer subscribes to `scan-updated` first and calls `get_state` only once the
subscription is in place: an event sent while the listener is still being registered reaches
nobody, so an earlier `get_state` answer could stay stale. After an event has arrived, a
`get_state` answer is ignored, since it may have been read before that event.

The TS mirror is `app/src/shell.ts`. Consumers must handle unknown `kind` and `reason` values
and treat `setting_up` as optional. How the state is saved to disk and when it refreshes is in
[state.md](state.md).
