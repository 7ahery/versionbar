# VersionBar

VersionBar inventories the developer tools on a machine and reports which copy of each one runs.

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

**Source**:
Where an Install was found: `path`, or a Provider id (`nvm`, `uv`, `py`, `rustup`, `dotnet`).
_Avoid_: Origin, location

**Via**:
The manager whose shim serves an Install (`corepack`, `volta`, `pyenv`).
_Avoid_: Shim owner, wrapper

**Provider**:
Python code that lists a version manager's Installs, including ones that are not on PATH.
_Avoid_: Plugin, adapter, manager integration

**Scan**:
One complete, live run of detection over all Tools, producing a ScanResult.
Refresh is the user action that triggers a Scan; `check` is the separate command that tests requirements against one.
_Avoid_: Poll, run

**ScanResult**:
The versioned JSON document a Scan produces: `schema_version`, `scanned_at`, `platform` and the Tools with their Installs.
_Avoid_: Report, snapshot, inventory
