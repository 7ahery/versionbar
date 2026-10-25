# VersionBar v1 spec: deviations and implementation decisions

Spec: [7ahery/versionbar#1](https://github.com/7ahery/versionbar/issues/1). Written only by the orchestrator; committed so it outlives the run and can feed the ADRs. Accepted entries amend the spec. IDs are never reused, and rejected entries stay as a record of what was considered.

DEV-1 and DEV-2 were first recorded as D1 and D2 in the spec's own "Deviations" section; this file is the record from here on.

## Deviations

Where the implementation differs from what the spec says. Status: `proposed`, `accepted` or `rejected`.

| ID | Requirement | Deviation | Reason | Impact | Status | Ticket | Merge |
|---|---|---|---|---|---|---|---|
| DEV-1 | Naming: "GitHub repo 7ahery/version-bar" | Repo is `7ahery/versionbar`; `version-bar` is only the local folder name | The actual GitHub repo name | URLs, release automation, bundle metadata use `7ahery/versionbar` | accepted | 01 (#2) | efcf4ad |
| DEV-2 | JSON contract tool fields `id`, `name`, `status`, `active`, `installs` | Extra field `notes: list[str]` (default `[]`, human text, not for parsing); the only diagnostic field. For `error`/`timeout` the first note is the failure message with decoded output; a failed non-active install adds a note and is omitted from `installs` | Spec requires notes (Store placeholders) and error messages, which need a home | One more tool field in schema_version 1; structured diagnostics can be added later non-breaking | accepted | 04 (#5), 07 (#8) | 981bcf8 |
| DEV-3 | Domain vocabulary: "Via: the manager whose shim serves an install (corepack, volta, pyenv)" | `nvm` is also a via value; a manager that has a provider uses the provider id as its via name. node.toml gets a top-level `[[via]] manager = "nvm"` (ticket 13 appends its node rules to that list) | The nvm-windows 2 shim on PATH is a shim; matching on via counts it and its held version once | Scan JSON can carry `via: "nvm"` | accepted | 16 (#18) | 9467488 |
| DEV-4 | JSON contract: "A missing tool is still listed, with active: null and no installs" | A `missing` (or error/timeout) tool may list provider-held installs in `installs`; `active` stays null | Story 8: see versions held off PATH even when nothing is active | Consumers must not assume `installs[0]` is active; check `active`. UI does not read `installs` yet | accepted | 16 (#18) | 9467488 |
| DEV-5 | App UI: "per-install actions (copy version, copy path, open containing folder, each through a scoped Rust command)"; ticket 25 AC2 | Copy version and Copy path use `navigator.clipboard` in the webview; only Open containing folder is a Rust command | DEC-14 already copies via the webview; a Rust clipboard needs a plugin not on the allowed list or a new crate; copying adds no process or filesystem access | IPC surface grows only by `allow-open-containing-folder`; copy failure shows "Could not copy. Select the text instead." | accepted | 25 (#29) | 3cd11d0 |

## Implementation decisions

One-way doors the spec left open, settled during implementation.

| ID | Decision | Reason | Alternatives rejected | Status | Ticket | Merge |
|---|---|---|---|---|---|---|
| DEC-1 | Scan JSON (schema_version 1) shape: see details | Spec left encodings open | — | accepted | 04–07 | 981bcf8 |
| DEC-2 | TOML definition keys `id`, `os`, `binaries`, `version_args`, `version_regex` (named `version` group required), `overrides.<os>`; unknown keys forbidden; no `encoding` key (detected from bytes per stream); git keeps vendor suffix (`2.55.0.windows.2`) | Small, strict, declarative format | Per-definition encoding key | accepted | 04 (#5) | c9c164f |
| DEC-3 | CLI shape: see details | Spec left exit codes and output rules open | — | accepted | 04–06 | ba13eaa |
| DEC-4 | Scan runs in a thread pool of 16, 5 s default timeout; real runner = Popen + tree kill (`taskkill /F /T` via `%SYSTEMROOT%`, killpg on POSIX), bounded 1 s drain; pipes closed after drain timeout on POSIX only | Bounded, predictable scan time | — | accepted | 07 (#8) | 981bcf8 |
| DEC-5 | `debug capture` (hidden) fixture format v1: see details | Fixtures must be byte-exact and reproducible | — | accepted | 05 (#6) | 4372439 |
| DEC-6 | Tooling: taplo via `uvx taplo==0.9.3`; actionlint via third-party `actionlint-py` wrapper; actions pinned to exact tags (not SHAs); `ty` alpha pinned by lock | Keep the toolchain uv/npm-only | SHA pinning | accepted | 03 (#4) | d1ceea0 |
| DEC-7 | App stack: Tauri 2.12, Vite 8, React 19.3, TS 6.0.3, Tailwind 4, shadcn setup only; npm workspace `app` with root lockfile; Rust 1.99.1 MSVC pinned; crate `tray-shell`; Rust CI Windows-only; capability guard test + cargo-deny bans shell plugin; display name = `productName` in `tauri.conf.json`; version guard test | Pinned, guarded shell | — | accepted | 20 (#23) | b920ca1 |
| DEC-8 | Contracts: `versionbar schema` emits the combined `CommandOutput` doc; `schema/` npm workspace (output/definition schema, output.d.ts); result models registered in `OUTPUT_MODELS`; all fields required, unknown keys forbidden. Adding a field or enum value is non-breaking and consumers must ignore unknown fields/values; remove/rename/retype is breaking. Deps json-schema-to-typescript@16.0.0, jsonschema (core dev) | One generated contract for all consumers | — | accepted | 10 (#10) | 44f7aec |
| DEC-9 | Core four: node "Node.js", python "Python" (binaries python, python3), uv "uv"; Store placeholders detected via the System seam without executing; placeholder-only → missing + note; unreadable alias fails closed; VersionBar's own venv hidden from scan and capture; capture redacts USERPROFILE to `%USERPROFILE%`; human `show` has an `Install` column | Store safety without running the redirector | — | accepted | 08 (#9) | 9e6c0a5 |
| DEC-10 | `versionbar check TOOL[@SPEC]...`: see details | Spec left the spec grammar and exit codes open | PEP 440 / semver libraries | accepted | 11 (#13) | 164a6f2 |
| DEC-11 | Definition `[[via]]` {manager, dirs, content_regex}; `.cmd`/`.bat` run via System32 `cmd.exe /d /e:on /v:off /s /c` with unsafe args and paths refused as launch_error. Full rules in `docs/definitions.md` | Manager attribution without code; safe batch execution | — | accepted | 10b (#11) | ecad988 |
| DEC-12 | Bundled core and live scan: see details | Spec left the bundle layout and IPC open | — | accepted | 21 (#24) | 1f10001 |
| DEC-13 | Public `versionbar config --json` is the second fixed core invocation (ADR 0011); config file and keys: see details | App needs preferences without Rust parsing TOML | Rust reads TOML | accepted | 12a (#14) | 7a6495d |
| DEC-14 | Recovery screens: see details | Spec left first-run and failure UX mechanics open | Opener plugin | accepted | 22 (#26) | 3cb600b |
| DEC-15 | App saved state: one file `%LOCALAPPDATA%\io.github.7ahery.versionbar\scan-state.json` = `{"format":1,"current":<raw scan>,"previous":<raw scan\|null>}`, written to `.tmp`, fsynced, renamed over; any invalid part discards the whole file; outcome not saved (restored state has `outcome: null`). Owner doc `docs/app/state.md` | One atomic rename rotates the pair; wrapper versioned apart from `schema_version` | Two files (current.json / previous.json) | accepted | 24 (#28) | 622bf17 |
| DEC-16 | Refresh coalescing: a request during a running scan queues exactly one follow-up scan shared by all requests (popup, tray menu, 30 min interval); supersedes ticket 21's "refresh during a scan is ignored" (DEC-12) | A dropped request can miss a config edit the running scan didn't see | Drop overlapping requests | accepted | 24 (#28) | 622bf17 |
| DEC-17 | Provider shape: `Provider` ABC with ClassVars `id` (also its source/via name), `name`, `os`, `tools`, and `locate(system, tool, timeout) -> Located(executables, notes)`; runs on the scan pool; the engine probes each executable with the tool definition; any exception becomes a note on that tool. Authoring guide `docs/providers.md` | Reuses probing, timeouts, decoding and failure notes; providers stay small | Providers return finished Installs (needed later for dotnet: an additive `Located` variant) | accepted | 16 (#18) | 9467488 |
| DEC-18 | `versionbar tools` → `ToolsResult{schema_version, platform, tools:[{id,name,os[],custom}], providers:[{id,name,os[],tools[]}]}`; all OSes and hidden tools included; registry order; invalid config → exit 3 | Minimal; fields can be added later (DEC-8) | Per-tool providers list and hidden flag | accepted | 16 (#18) | 9467488 |
| DEC-19 | Dedup/provenance: PATH always wins. A provider path equal to a PATH hit (normalised, case-insensitive on Windows) is that PATH install, probed once, `source: path`; two providers naming one file → first keeps it; a PATH install whose `via` equals a provider id is that manager's shim, so the provider install with the same version is dropped | Active install stays what typing the command runs; no contract change; covers nvm 2 shim and nvm 1 NVM_SYMLINK without symlink resolution | Provider id as source; `System.real_path` symlink resolution | accepted | 16 (#18) | 9467488 |
| DEC-20 | `System.list_dir` added (FileNotFoundError/NotADirectoryError = absent; other OSError = unreadable); hidden `debug capture <tool> --source <provider>` + capture failure value `unknown-source` (exit 2) | Providers need directory listing (ADR 0004 lists it); provider-held installs need real fixtures | — | accepted | 16 (#18) | 9467488 |
| DEC-21 | `open_containing_folder { path }` accepts only a drive-absolute `X:\` path with backslashes, no control characters, none of `" * ? < > \| /`, no colon but the drive's, naming an existing file; runs only `%SystemRoot%\explorer.exe /select,"<path>"` (never the path itself). Docs `docs/app/actions.md` | Rust cannot check paths against the scan (hard rule 2); UNC/device paths would let the webview make Explorer contact arbitrary hosts | Also allow UNC paths and directories (tools on network shares can't be revealed) | accepted | 25 (#29) | 3cd11d0 |

## Details

### DEC-1: scan JSON

`platform` = `"windows"`/`"linux"`; `scanned_at` RFC 3339 UTC with `Z`; `installs` = all deduped PATH hits with the active one first (`active` is one of them; "Others" = len−1); `via`/`raw` explicit null; `raw` = decoded stripped output, CRLF→LF. Notes per DEV-2; timeouts keep partial output.

### DEC-3: CLI shape

Bare `versionbar` = `list`; root `--json` accepted; all output UTF-8; piped human tables never wrap; NO_COLOR/FORCE_COLOR via the System seam; `show <tool>...` (`--json` = list envelope filtered); exit 2 = usage error (unknown id; "<id> is not available on <os>" for other-OS ids); relative/empty PATH entries skipped; same-folder `git.exe` + `git.cmd` are distinct installs. Exit 3 = invalid config (DEC-13).

### DEC-5: fixture format v1

`format: 1`, tool, args, exit_code, `stdout_b64`/`stderr_b64` (authoritative), encoding guess, `*_text`, strict provenance without hostname. Files `<os>-<tool>-<version>.json`. Outcomes: unknown-tool/unsupported-os → exit 2; not-found/timeout/launch-error/write-failed → exit 1. `capture.yml` is workflow_dispatch only and stays green regardless of outcomes.

### DEC-10: check

Ops `>= > <= < ==`, comma = AND; bare version, `!=`, `~=`, `=` are usage errors. Exit 0 all pass / 1 any unmet (incl. missing/error/timeout) / 2 usage (plain stderr, no scan). In-house comparator: leading `\d+(\.\d+)*`, trailing zeros ignored, `==2.55` ≠ 2.55.1; pre-release suffixes (a/alpha/b/beta/rc/c/dev/pre/preview) rank just below the release; other suffixes ignored; no leading number → `not-comparable`. `CheckResult` = schema_version, scanned_at, platform, passed, requirements[] (requirement, tool, spec|null, passed, outcome passed/unmet/not-comparable/missing/error/timeout, version|null, path|null, message). Command name in text comes from `PROG`.

### DEC-12: bundled core and live scan

Bundle `<resource_dir>/core/` (pyproject, uv.lock, .python-version, README.md, src/). Env `%LOCALAPPDATA%\io.github.7ahery.versionbar\core-env` (+ `pycache`). Invocation `uv run --frozen --no-dev --managed-python --project <res>\core -- versionbar list --json` with UV_PROJECT_ENVIRONMENT, PYTHONPYCACHEPREFIX, CREATE_NO_WINDOW; VIRTUAL_ENV and the override lists in `docs/app/bundled-core.md` removed. IPC `get_state`/`refresh` + `scan-updated` event (popup listens before `get_state`); state `{scanning, current, previous, outcome}`, outcome ok/uv_missing/failed (reason launch|timeout|exit|malformed|incompatible). Rust holds scan JSON as an opaque RawValue; state in memory (persistence is ticket 24); 30 s timeout, taskkill bounded 1 s; serde/serde_json(raw_value) direct deps; `app/src/shell.ts` hand-mirrors ShellState.

### DEC-13: config and preferences query

Config at `%APPDATA%\versionbar\config.toml` (platformdirs roaming). Keys `timeout`, `pinned`, `order`, `hidden`, `[timeouts]`, `[app] update_check`, `[[tools]]`. Timeout precedence `timeouts.<id>` > `timeout` > 5 s; a custom tool with a built-in id replaces it in place; list order pinned → order → rest. `ConfigResult` = {schema_version, config_path, config_exists, problems, preferences|null}. Invalid config → exit 3 for list/show/check/config (so the app scan fails too). Starter template `core/src/versionbar/starter_config.toml`.

### DEC-14: recovery screens

`ShellState.setting_up: bool`. No-arg IPC `open_uv_docs` (+ `allow-open-uv-docs`) opens the fixed uv install docs URL via `%SystemRoot%\explorer.exe` (no opener plugin); clipboard via `navigator.clipboard`. First run = core-env missing or `Scanner.unsettled` (set by a first-run scan, cleared on success) → 180 s timeout + setting_up. Tray warning badge + tooltip while uv is missing, cleared by the next scan that finds uv. Recovery screens only when there is no current result; download note only on setup and timeout/exit failures; after installing uv the user restarts VersionBar. User doc `docs/troubleshooting.md`.
