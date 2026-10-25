# Writing providers

A provider finds the installs a version manager holds, including ones that are not on PATH (ADR 0003). Tools whose installs are all on PATH need no provider: write a [definition](definitions.md) instead.

A provider only says **where** the installs are. The engine does the rest, the same way for every provider: it runs each install with its tool's own version command (the tool's definition: `version_args`, `version_regex`, timeout, decoding, `via` rules), merges the results with the PATH installs, and keeps any failure local. Adding a provider needs no engine change.

## The class

One `Provider` subclass (`core/src/versionbar/provider.py`) in `core/src/versionbar/providers/`, added to `builtin_providers()` in `core/src/versionbar/providers/__init__.py`. The built-in `nvm` provider (`providers/nvm.py`) is the reference.

```python
class NvmWindows(Provider):
    id = "nvm"              # the `source` of its installs; also the `via` name of its shims
    name = "nvm-windows"    # display name, also the prefix of its notes
    os = ("windows",)       # never called on other OSes
    tools = ("node",)       # tool ids it reports installs for

    def locate(self, system: System, tool: str, timeout: float) -> Located:
        ...
        return Located(executables=[...], notes=[...])
```

`locate` is called once per scan for each tool in `tools` that the scan includes, on the scan's thread pool.

- **Find the manager through its environment variables**, never fixed paths (`NVM_HOME`, not `%LOCALAPPDATA%\nvm`). Strip surrounding quotes and spaces, and ignore a value that is not absolute.
- **Use only `system`** (hard rule 9): `getenv`, `list_dir`, `is_executable`, `read_file_head`, `read_file`, `run`. Any command you run gets `timeout`.
- **Return executables**: absolute paths of the installs' programs, in the order to report them (nvm: newest version first, compared numerically). The engine runs each one; the version reported is what it prints.
- **A manager that is not there contributes nothing**: variable unset, or its folder missing (`list_dir` raises `FileNotFoundError` or `NotADirectoryError`). Return an empty `Located()` and no note.
- **Notes are for data that should be an install but is not**, such as a version folder without its executable. Start each with the provider's name (`nvm-windows: …`); they are human text, never parsed.
- **Let unexpected errors propagate.** A manager folder that exists but cannot be read (`PermissionError`), or anything else `locate` raises, becomes the note `<name>: could not list installs: <error>` on each of its tools. Nothing else is lost.

## What the engine does with the result

- Installs are added to the tool's `installs` after the PATH installs, providers in `builtin_providers()` order, with `source` set to the provider's `id`. They never become `active`: the active install is always the first PATH hit, whatever the manager has selected, and `check` only looks at the active install.
- A tool with no PATH install stays `missing` (or `error`/`timeout` if its PATH install failed), with the provider's installs listed and `active: null`.
- **One install is reported once:**
  - A path that is also a PATH hit is the PATH install (`source: path`) and is not run twice. Paths compare like PATH hits (case-insensitive, normalised on Windows).
  - A path two providers both name belongs to the first.
  - A PATH install whose `via` is the provider's `id` is that manager's shim, serving one of the manager's installs. The provider's install with the same version is that one, so it is dropped and the PATH install stays. This is why the shim rule in the tool's definition uses the provider's `id` as its `manager` (node: `manager = "nvm"`, `dirs = ["{NVM_HOME}/.nodejs", "{NVM_SYMLINK}"]`).
- An install that fails (cannot start, exits non-zero, prints no version, times out) is left out and adds a note `<name>: <path> …`, worded like a PATH failure.

`versionbar tools` lists every provider with its `id`, `name`, `os` and `tools` (the `ToolsResult` model), with no change needed when one is added.

## Fixtures and the capture route

Every provider needs a real capture of an install it found (hard rule 4). Record it with the provider itself, on a machine where the manager holds at least one install:

```sh
uv run --project core versionbar debug capture node --source nvm --out core/tests/fixtures/nvm
```

`--source <provider id>` captures the first install that provider reports, instead of the active PATH install, and writes `provenance.notes` = `reported by the <name> provider (source <id>), not from PATH`. Everything else is the normal [capture format](capture.md). Store provider captures under `core/tests/fixtures/<provider id>/`.

Tests go through the CLI seam (`core/tests/test_providers.py`): the fake system's folders and environment are synthetic (`add_executable` creates the files, and so the folders `list_dir` sees; `add_folder` adds an empty folder, `add_unlistable` an unreadable one), and every version command answers with a real capture. Cover the manager present and absent, an unusual location, several installs, overlap with PATH, and each failure.

The `Capture tool output` workflow cannot use `--source`: runner images have no version managers worth capturing, and the workflow never installs anything.

## nvm-windows

- nvm-windows 2 (observed: 2.0.1, installed under `%LOCALAPPDATA%\Author Software\nvm`) keeps each version in `%NVM_HOME%\installs\v<version>\node.exe` and puts `%NVM_HOME%\.nodejs` (a junction to its shim folder) on PATH; `NVM_SYMLINK` is unset. The shim's `node.exe` answers with the selected version.
- nvm-windows 1 keeps versions in its root, `%NVM_HOME%\v<version>\` by default, and points `NVM_SYMLINK` (a link on PATH) at the selected one. Both layouts are read. A version-1 root moved away from `NVM_HOME` with `root:` in `settings.txt` is not read.
- Only folders named `v<major>.<minor>.<patch>` are versions; anything else (`.cache`, `installs`, `nvm.exe`) is ignored.
