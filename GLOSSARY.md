# VersionBar

VersionBar inventories the developer tools on a machine and reports which installation of each one runs.

## Language

**Tool**:
Something VersionBar detects, such as git, node or nvm. Defined declaratively.
_Avoid_: Program, app, package

**Install**:
One concrete installation of a Tool on the machine, with a version, path and Source, and optionally a Via and the raw version output.
_Avoid_: Instance, copy, binary

**Active install**:
The Install that runs when you type the Tool's command: the first resolvable hit on PATH.
_Avoid_: Default, current, primary

**Store placeholder**:
A Microsoft Store App Execution Alias, such as `python.exe` in `WindowsApps`, that only offers to install the app from the Store. Recognised without running it and never an Install.
_Avoid_: Stub install, Store Python (that is a real Install from the Store)

**Source**:
Where an Install was found: `path`, or a Provider id (`nvm`, `uv`, `py`, `rustup`, `dotnet`).
_Avoid_: Origin, location

**Via**:
The manager whose shim serves an Install (`corepack`, `volta`, `pyenv`).
_Avoid_: Shim owner, wrapper

**Wrapper**:
A `.cmd` or `.bat` file on PATH that starts the real program, such as `npm.cmd` or `code.cmd`. It is what typing the command runs, so an Install's path is the wrapper's.
_Avoid_: Launcher, script (the extensionless script beside a wrapper is never run)

**Shim**:
A Wrapper or executable that a manager puts on PATH to forward to the version it selects. Installs reached through one carry a Via.
_Avoid_: Proxy, stub

**Provider**:
Python code that lists a version manager's Installs, including ones that are not on PATH.
_Avoid_: Plugin, adapter, manager integration

**Scan**:
One complete, live run of detection over all Tools, producing a ScanResult.
Refresh is the user action that triggers a Scan; `check` is the separate command that tests requirements against one.
_Avoid_: Poll, run

**Config file**:
The user's optional TOML file of settings (custom Tools, hidden Tools, timeouts, pins and order, the app's update check), shared by the CLI and the app and read on every run.
_Avoid_: Settings file, preferences file

**Custom tool**:
A Tool defined in the Config file rather than built in, in the same definition format. One with a built-in's id replaces that built-in.
_Avoid_: User tool, plugin

**Preferences**:
The part of the Config file the app needs, reported by the preferences query (`config --json`): the update check, pins and order.
_Avoid_: Options

**ScanResult**:
The versioned JSON document a Scan produces: `schema_version`, `scanned_at`, `platform` and the Tools with their Installs.
_Avoid_: Report, snapshot, inventory
