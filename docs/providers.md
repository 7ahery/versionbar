# Writing providers

A provider finds the installs a version manager holds, including ones that are not on PATH (ADR 0003). Tools whose installs are all on PATH need no provider: write a [definition](definitions.md) instead.

A provider usually only says **where** the installs are. The engine does the rest, the same way for every provider: it runs each install with its tool's own version command (the tool's definition: `version_args`, `version_regex`, timeout, decoding, `via` rules), merges the results with the PATH installs, and keeps any failure local. A manager that already knows each install's exact version without running it (the .NET host lists its SDKs, which all run through one `dotnet.exe`) reports **finished installs** instead, and the engine reports them as they are. Adding a provider needs no engine change.

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
        return Located(executables=[...], notes=[...], installs=[ProvidedInstall(version, path), ...])

    def listing(self, system: System, tool: str) -> Sequence[str] | None:
        ...  # optional: the command `locate` reads, for `debug capture --source`
```

`locate` is called once per scan for each tool in `tools` that the scan includes, on the scan's thread pool.

- **Find the manager through its environment variables**, never fixed paths (`NVM_HOME`, not `%LOCALAPPDATA%\nvm`). One exception: a manager's documented home-relative default derived from an environment variable (rustup: `%USERPROFILE%\.rustup`, because rustup never sets `RUSTUP_HOME` itself). Strip surrounding quotes and spaces, and ignore a value that is not absolute.
- **Use only `system`** (hard rule 9): `getenv`, `list_dir`, `is_executable`, `read_file_head`, `read_file`, `run`. Any command you run gets `timeout`.
- **Return executables**: absolute paths of the installs' programs, in the order to report them (nvm: newest version first, compared numerically). The engine runs each one; the version reported is what it prints.
- **Or return finished installs** (`installs`, a sequence of `ProvidedInstall(version, path)`, both in `core/src/versionbar/provider.py`) when the manager itself states each install's exact version and running each one is impossible or would say nothing new (several installs behind one host executable). Nothing is run for them. `version` is the exact version as the manager names it. `path` is the absolute path of the install itself (for an SDK, its own folder), never the host executable several installs share: installs are told apart by path. A provider may return both kinds; executables are reported first, then finished installs, each in the order given.
- **Declare the listing command** you parse by overriding `listing(system, tool)`: return its argv, the manager's executable as an absolute path first (for example `[<dotnet.exe>, "--list-sdks"]` or `[<py.exe>, "-0p"]`), or `None` when the manager is not on this machine. `locate` should run exactly that command, so its recorded output is what the provider reads. `debug capture --source` records it (see below). Providers that only read folders (nvm, rustup) keep the default `None`.
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
- **Finished installs** (`Located.installs`) are reported as given, with `source` set to the provider's `id`, `via: null` and `raw: null`, without running anything. They take part in the rules above by their `path`: one equal to a PATH hit, or to a path an earlier provider (or the same one) already named, is dropped; distinct versions sharing one host executable are never merged, because each has its own path. One more rule keeps PATH winning: a PATH install whose version equals a finished install's version, and whose executable's folder contains that install's path, is the host running that very install (`C:\Program Files\dotnet\dotnet.exe` answering `10.0.402` and the SDK `C:\Program Files\dotnet\sdk\10.0.402`), so the finished install is dropped and the PATH install stays. The same version elsewhere, or another version in the same folder, stays. "Under the PATH host" means inside the PATH executable's own folder, with no link resolution, so a symlinked layout (Ubuntu's `/usr/bin/dotnet` pointing into `/usr/lib/dotnet`) can list the active version twice; the dotnet provider (#40) is registered for Windows only in v1. This rule applies only to finished installs: an executable a provider reports is its own program, told apart by path alone.
- An install that fails (cannot start, exits non-zero, prints no version, times out) is left out and adds a note `<name>: <path> …`, worded like a PATH failure.
- A provider whose `locate` raises, or returns data the engine cannot read (an install that is not a `ProvidedInstall`, say), adds the note `<name>: could not list installs: <error>` to that tool and contributes nothing else to it; PATH installs and other providers are untouched.

`versionbar tools` lists every provider with its `id`, `name`, `os` and `tools` (the `ToolsResult` model), with no change needed when one is added.

## Fixtures and the capture route

Every provider needs a real capture of what it reads (hard rule 4). Record it with the provider itself, on a machine where the manager holds at least one install:

```sh
uv run --project core versionbar debug capture node --source nvm --out core/tests/fixtures/nvm
```

`--source <provider id>` captures, instead of the active PATH install:

- the provider's **listing command**, when `listing()` names one here: it is run as given and recorded as `<os>-<tool>-<provider id>-listing.json`, with `provenance.notes` = `listing command of the <name> provider (source <id>), whose output it reads <tool> installs from; not a version command`. Tests replay it as the manager executable's answer to those arguments.
- otherwise the **first install** the provider reports (its first executable), run with the tool's version command, with `provenance.notes` = `reported by the <name> provider (source <id>), not from PATH`.

Everything else is the normal [capture format](capture.md). Store provider captures under `core/tests/fixtures/<provider id>/`. `--timeout <seconds>` gives a slow command longer than the default 5 s.

Tests go through the CLI seam (`core/tests/test_providers.py`): the fake system's folders and environment are synthetic (`add_executable` creates the files, and so the folders `list_dir` sees; `add_folder` adds an empty folder, `add_unlistable` an unreadable one), and every version command answers with a real capture. Cover the manager present and absent, an unusual location, several installs, overlap with PATH, and each failure.

The `Capture tool output` workflow takes the same `source` (and `timeout`) as optional inputs, for managers the runner image already has (the .NET host and its SDKs, the py launcher); it never installs one ([docs/capture.md](capture.md)).

## nvm-windows

- nvm-windows 2 (observed: 2.0.1, installed under `%LOCALAPPDATA%\Author Software\nvm`) keeps each version in `%NVM_HOME%\installs\v<version>\node.exe` and puts `%NVM_HOME%\.nodejs` (a junction to its shim folder) on PATH; `NVM_SYMLINK` is unset. The shim's `node.exe` answers with the selected version.
- nvm-windows 1 keeps versions in its root, `%NVM_HOME%\v<version>\` by default, and points `NVM_SYMLINK` (a link on PATH) at the selected one. Both layouts are read. A version-1 root moved away from `NVM_HOME` with `root:` in `settings.txt` is not read.
- Only folders named `v<major>.<minor>.<patch>` are versions; anything else (`.cache`, `installs`, `nvm.exe`) is ignored.

## rustup (Rust)

- Reports the tools `rustc` and `cargo`. rustup is never run: even `rustup toolchain list` installs the toolchain pinned by a `rust-toolchain.toml` in the working directory, which VersionBar must never do. The provider lists `<RUSTUP_HOME>\toolchains` instead. `RUSTUP_HOME` is used when set (absolute); otherwise rustup's documented default `%USERPROFILE%\.rustup`. A relative `RUSTUP_HOME` is ignored, and the default is not used in its place.
- That default is a deliberate exception to "find the manager through its environment variables": rustup never sets `RUSTUP_HOME` itself, so nearly every machine relies on the default. A manager's documented home-relative default derived from an environment variable (`USERPROFILE`) is allowed; a literal path is not.
- Each folder in `toolchains` is one install: `<folder>\bin\rustc.exe` and `<folder>\bin\cargo.exe`, run with the tool's own version command and reported in folder-name order. The proxies in `~\.cargo\bin` are PATH hits and stay `active`; they are not duplicated. A folder without the tool's executable adds the note `rustup: <folder> has no bin\<tool>.exe, so it is not an install`.
- A missing home or `toolchains` folder, or an empty one, adds nothing and says nothing. An unreadable `toolchains` folder is the note `rustup: could not list installs: <why>`; PATH installs are untouched.
- Windows only for now: the toolchain layout is only confirmed there. The provider reads no output of its own, so the fixtures are the toolchain installs' real version captures, recorded with `versionbar debug capture rustc --source rustup` (and `cargo`) from a neutral folder (`core/tests/fixtures/rustup/windows-rustc-1.99.1.json`, `windows-cargo-1.99.1.json`).

## uv (Python)

- Runs `uv python list --no-config --only-installed --output-format json` (`--no-config` so a `uv.toml` or `pyproject.toml` in the working directory cannot hide installs) with the `uv` that typing `uv` runs (PATH), else `%UV_INSTALL_DIR%\uv.exe`. `--only-installed` means the catalog of downloadable Pythons is never read, and nothing is downloaded. uv not found: nothing is added and nothing is said.
- uv lists one managed Python several times (the install, its launcher in the user's bin folder such as `~\.local\bin\python3.14.exe`, and a minor-version link folder). Only the entry in the folder named after its `key` (`<uv python dir>\<key>\python.exe`) is the install, so each Python is reported once, with its exact version from running it. Entries uv found elsewhere (PATH, the registry) are not uv's and are left to PATH and the py launcher. uv's own folder rules (`UV_PYTHON_INSTALL_DIR` and the rest) apply because uv answers, not VersionBar.
- Windows only for now: the only real capture of the listing is from Windows (`core/tests/fixtures/uv/windows-uv-python-list-0.12.23.json`). The uv provider does not declare that listing through `listing()` yet, so `debug capture` cannot record it; that file is a seed made from the real command's output (user name replaced by `dev`), as its `provenance` says. Re-seed it the same way when uv's output format changes.
- A failing listing (cannot start, non-zero exit, timeout, not JSON) is the note `uv: could not list installs: <why>` on Python; PATH installs are untouched.

### Active versus held Pythons

`active` is only what typing `python` runs. A Python that uv (or the py launcher) holds is listed in `installs` with its own `source`, and never becomes active, even when it is the only Python on the machine. So a machine whose `python` is only a Microsoft Store placeholder stays `missing` with `active: null`, the placeholder notes, and the managed Pythons listed. `check` says `python is not active: not found on PATH ... (2 installs found off PATH)` there, instead of "not installed".
