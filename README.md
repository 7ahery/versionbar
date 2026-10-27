# VersionBar

Inventories the dev tools installed on a machine. The `versionbar` CLI (Python core) is the product; a Windows tray app is one consumer of it.

**Status: M1.** The CLI detects the core four live: git, node, python and uv. It also lists the Node.js versions nvm-windows holds off PATH, and `versionbar tools` lists every tool and provider it knows. More tools and providers arrive in later slices. The tray app launches and opens its popup, which does not show scan results yet.

## Usage

```sh
versionbar               # same as `versionbar list`
versionbar list          # table: each tool's active version, path and count of other installs
versionbar show python node  # every install of the given tools, the active one first (also: `--json`)
versionbar list --json   # machine-readable ScanResult (also: `versionbar --json`)
versionbar check git 'node@>=20' 'python@>=3.12,<4'  # exit 0 only if every requirement holds
versionbar config        # where the config file is and what it sets (also: `--json`)
versionbar tools         # every tool and provider VersionBar can detect, on every OS (also: `--json`)
versionbar schema        # JSON Schema of every --json output
versionbar --help        # every command has --help
```

Every run scans the machine live; nothing is cached. Human output uses colour only on a terminal (or when `FORCE_COLOR` is set); it is plain when piped or when `NO_COLOR` is set, and piped tables never wrap, so each tool stays on one line. `--json` output never contains colour or decoration. All output is UTF-8.

### JSON output

```json
{
  "schema_version": 1,
  "scanned_at": "2026-10-23T21:09:34.002752Z",
  "platform": "windows",
  "tools": [
    {
      "id": "git",
      "name": "Git",
      "status": "found",
      "active": { "version": "2.55.0.windows.2", "path": "C:\\Program Files\\Git\\cmd\\git.exe", "source": "path", "via": null, "raw": "git version 2.55.0.windows.2" },
      "installs": [ "...the same install..." ],
      "notes": []
    }
  ]
}
```

- `schema_version` is an integer bumped only on breaking changes. `scanned_at` is an RFC 3339 UTC timestamp. `platform` is the OS id (`windows`, `linux`).
- `status` is one of `found`, `missing`, `error`, `timeout`. A missing tool is still listed, with `active: null`; its `installs` are empty unless a provider found some off PATH (see below).
- `active` is the install that runs when you type the command: the first PATH hit, following PATHEXT on Windows (PATH order first, then PATHEXT order; extensionless files are never run). `installs` lists every install found, the active one included.
- Active versus other installs: the active install is the first hit, and it is also `installs[0]`. Every other entry in `installs` is an *other install*: a different file on PATH that the active one shadows, or an install a version manager holds (see Providers below). `list` shows how many (`len(installs) - 1`, or all of them when nothing is active). A binary reached through several PATH entries (different case on Windows, trailing separators, `.`/`..`, quotes) counts once; genuinely different files, such as `git.exe` and `git.cmd` in one folder or two folders, stay separate. Symlinks are not resolved.
- An other install whose version command fails is left out of `installs` and explained in `notes`; if the active install fails, the tool's `status` is `error` or `timeout`.
- `versionbar show <tool>...` prints the same `ScanResult`, limited to the requested tools (in the order given, repeats dropped). An unknown id exits with code 2 and lists the known ids on stderr; nothing is written to stdout.
- `source` is `path` for installs found on PATH, or the id of the provider that found it (`nvm`). `via` and `raw` are optional (`null` when absent); `raw` is the version output the version was read from.
- `notes` are human-readable diagnostics explaining a status (for example why a tool is missing, or the captured message of a failed version command). They are for people and logs, not for parsing. They are the only diagnostic field; see below for what each status puts there.

`versionbar schema` prints the JSON Schema (draft 2020-12) of every `--json` output, generated from the core's Pydantic models. The same schema and the UI's TS types are committed under [`schema/`](schema/README.md), which also describes the compatibility rules.

### Requirement checks

`versionbar check <tool>[@<spec>]...` scans live (only the tools named) and tests each requirement against the tool's **active install**; an inactive install, such as another version a manager holds, never satisfies a requirement on its active one's behalf.

- `git` means "must be installed". `git@>=2.40` also needs a version. A spec is one or more clauses joined by commas, all of which must hold: `>=`, `>`, `<=`, `<` or `==` followed by a dotted number, e.g. `>=3.12,<4`. Spaces around clauses are ignored. Quote requirements in the shell, because `>` and `<` are redirections: `versionbar check 'node@>=20' 'python@>=3.12'`.
- Versions are compared by their leading dot-separated numbers, numerically, with missing trailing parts counted as 0. Anything after them is ignored: git's `2.55.0.windows.2` is 2.55.0, OpenSSH's `9.5p2` is 9.5. A pre-release marker straight after the numbers (`a`, `alpha`, `b`, `beta`, `c`, `rc`, `pre`, `preview`, `dev`, any case, optionally after `-` or `.` and followed by digits) ranks just below that release: `3.14.0rc1` fails `>=3.14` but passes `>=3.13` and `<3.14`; two pre-releases of the same numbers compare equal. `==2.55` therefore matches `2.55.0` but not `2.55.1`; write `>=2.55,<2.56` for "any 2.55.x". A version with no leading number can still satisfy a presence-only requirement, but fails any spec with outcome `not-comparable`. There is no `!=`, `~=` or bare-version form (`node@20` is a usage error, not a guess).
- Exit codes: `0` every requirement passed; `1` at least one failed, including a missing, erroring or timed-out tool; `2` the request is malformed (no requirements, bad syntax, unknown tool, a tool that does not exist on this OS). Usage errors are plain text on stderr even with `--json`, list every problem found, and run no scan.
- Human output has one line per requirement (`pass` or `FAIL`, the requirement as written, and the reason). `--json` prints a `CheckResult`:

```json
{
  "schema_version": 1,
  "scanned_at": "2026-10-23T21:04:52Z",
  "platform": "windows",
  "passed": false,
  "requirements": [
    {
      "requirement": "git@>=3", "tool": "git", "spec": ">=3", "passed": false,
      "outcome": "unmet", "version": "2.55.0.windows.2",
      "path": "C:\\Program Files\\Git\\cmd\\git.exe",
      "message": "git 2.55.0.windows.2 does not satisfy >=3"
    }
  ]
}
```

`outcome` is `passed`, `unmet`, `not-comparable`, `missing`, `error` or `timeout`; `version` and `path` are `null` when the tool has no active install; `message` is for people. The same requirement may appear several times (each is reported, the tool is scanned once). `schema_version` is the same counter as in a scan result; new fields or outcomes are non-breaking under the [compatibility rules](schema/README.md).

### Providers: installs a version manager holds

Providers find the installs a version manager keeps, including ones not on PATH, and add them to `installs` after the PATH ones with the provider's id as `source`. They never change which install is active: that is always the first PATH hit, whatever the manager has selected. `check` therefore never counts them. v1 has one provider:

- `nvm` (nvm-windows, Windows): every Node.js version in `%NVM_HOME%\installs\` (nvm-windows 2) or `%NVM_HOME%\` (nvm-windows 1), newest first. `NVM_SYMLINK` is not needed. Without `NVM_HOME`, or if that folder is gone, it adds nothing.

One install is reported once. A file a provider names that is also a PATH hit stays the PATH install (`source: path`). nvm's shim folder (`%NVM_HOME%\.nodejs`) or `NVM_SYMLINK` on PATH serves one of nvm's versions: that PATH install gets `via: nvm`, and nvm's copy of the same version is not listed again. Each held install is run with its tool's own version command, so the version reported is what it prints, not its folder name. A provider that cannot read its manager's folders, a version folder without its executable, and a held install that fails, hangs or prints no version each add a note (prefixed with the provider's name) and lose nothing else. `versionbar tools` lists every provider with the tools and OSes it covers; [docs/providers.md](docs/providers.md) explains how to write one.

### Failures and partial results

A scan always completes and always lists every tool (except those the config hides); one broken or slow tool never stops the others from being reported. The exit code of `list` and `show` does not depend on tool statuses. An invalid config file stops every scanning command with exit code 3 before anything runs (see [docs/config.md](docs/config.md)).

| What happened | `status` | `active`, `installs` | `notes` |
| --- | --- | --- | --- |
| No binary on PATH | `missing` | `null`, `[]` (or the installs providers found) | `not found on PATH (looked for: …)` |
| Active install did not answer within 5 s (or the configured timeout) | `timeout` | `null`, `[]` (or the installs providers found) | `<path> did not answer within <n> s`, plus `: <its output>` if it printed anything before it was killed |
| Active install could not be started | `error` | `null`, `[]` (or the installs providers found) | `could not run <path>: <OS error>` |
| Active install exited non-zero | `error` | `null`, `[]` (or the installs providers found) | `<path> exited with code <n>: <its output>` |
| Active install printed no recognisable version | `error` | `null`, `[]` (or the installs providers found) | `<path> printed no version: <its output>` |
| An other install failed in any of these ways | `found` | that install left out | one note per failed install, same wording |
| Only Microsoft Store placeholders on PATH | `missing` | `null`, `[]` | `only Microsoft Store placeholders found on PATH (looked for: …)`, then one note per placeholder |
| A provider failed, or one of its installs did | unchanged | that install left out | `<provider name>: …`, after the PATH notes; installs from PATH and other providers stay |

### Microsoft Store placeholders and VersionBar's own Python

Windows puts `python.exe` and `python3.exe` App Execution Aliases in `%LOCALAPPDATA%\Microsoft\WindowsApps` that do not run Python: they belong to App Installer and offer to install Python from the Store (run from a terminal, they exit with code 9009). VersionBar recognises them from the alias data stored in the file itself (the App Installer's `PythonRedirector` app), without running them, and never reports them as installs. Each placeholder found gets a note, also when a real Python is found beside it; if a placeholder comes before the active install on PATH, its note says that typing the command runs the placeholder instead. Other aliases in that folder, including real tools from the same package such as `winget`, are run normally.

The core itself runs on a uv-managed Python, and `uv run`/`uvx` put that environment's scripts folder first on PATH. That folder is left out of resolution, so the Python running VersionBar is never reported as your active Python; only the PATH you have is inspected. The rule is about the virtual environment VersionBar runs in, whoever created it: if you install `versionbar` into a project venv of your own and run it with that venv activated, that venv's `Scripts` (or `bin`) folder is hidden too, and its Python is not reported. Install it with `uv tool install` or run it with `uvx` to see the venv's Python.

If the data of a `python.exe` or `python3.exe` alias cannot be read, VersionBar assumes it is a placeholder, does not run it, and says so in a note: skipping a real Python costs a note, running a placeholder could open the Store.

"Its output" is everything the command printed, stdout then stderr, decoded. Version commands run in parallel (up to 16 at once), each with a 5-second timeout (configurable); when one times out, its whole process tree is killed (so a hung program started by a `.cmd` shim cannot stall the scan). Output is decoded per stream: UTF-16 (with a BOM, or detected by its NUL bytes, as `wsl --version` prints it) or UTF-8, with Windows line endings normalised to `\n`; a version printed only on stderr (as `ssh -V` does) is found too. Captures keep the raw bytes, so every decoding case replays exactly in tests.

### Scan timing

The target is a full scan in about a second. Typical timing on the development machine (Windows 11, 2026-10-24), scanning 15 real tools (18 version commands, including `npm.cmd` and `code.cmd`) in-process, median of five runs: **0.35 s** in parallel versus 0.90 s one at a time. Python and uv start-up add to this for a CLI invocation.

The first full scan of the built-in core four (git, node, python and uv; four version commands, two git installs among them; the two Store placeholders are not run), same machine, 2026-10-24, median of five runs: **0.07 s** in-process and **0.65 s** for a whole `versionbar list --json` invocation, which is mostly interpreter start-up. This is a measurement, not a test: the suite proves parallelism with synchronisation in the fake system rather than with wall-clock thresholds.

## Config

An optional TOML file (`%APPDATA%\versionbar\config.toml` on Windows, `~/.config/versionbar/config.toml` on Linux), read on every run and shared with the tray app, adds custom tools in the definition format, hides tools from `list`, pins and orders them, sets global and per-tool timeouts, and turns off the app's update check. `versionbar config` prints its path and the settings in effect. Every key, the ordering rule and the error format: [docs/config.md](docs/config.md).

## Tool definitions and fixtures

Built-in tools are TOML files in `core/src/versionbar/definitions/` (keys: `id`, `name`, `os`, `binaries`, `version_args`, `version_regex` with a named `version` group, optional `[[via]]` shim rules, and optional per-OS `overrides.<os>` replacing `binaries`, `version_args`, `version_regex` or `via`). The engine has no per-tool code. See [docs/definitions.md](docs/definitions.md) for every key, Windows wrappers and shim attribution.

Tests run the CLI over a fake system (`core/tests/fakes.py`) whose command output comes only from real captures in `core/tests/fixtures/<tool>/` (and `fixtures/<provider>/` for installs a provider found). Each capture records its provenance (OS, resolved path, exact command, date) beside the output; see `docs/capture.md` to record one.

## Setup

Prerequisites: [uv](https://docs.astral.sh/uv/) and Node.js 24+ with npm 11. uv downloads the pinned Python (3.14) itself, so do not install a system Python. The tray app also needs Rust (rustup; `rust-toolchain.toml` selects the exact toolchain) and, on Windows, the MSVC Build Tools. Windows contributors: see [docs/setup/windows.md](docs/setup/windows.md).

```sh
git clone https://github.com/7ahery/versionbar
cd versionbar
npm install                                # UI and Tauri CLI dependencies (npm workspace `app/`)
npm run cli -- --help                      # first run creates core/.venv
npm run doctor                             # confirm the toolchain meets the repo pins
cargo install cargo-deny@0.20.2 --locked   # once, for `npm run lint` (same version as CI)
```

Install the CLI from a checkout:

```sh
uv tool install ./core
versionbar --help
```

## Tray app

`app/` holds the Windows tray app: the React/TS popup UI in `app/src/` (Vite, React 19, strict TypeScript, Tailwind, shadcn/ui, lucide icons) and the Tauri Rust shell in `app/src-tauri/`. The root `package.json` is an npm workspace whose only member is `app`, so one `npm install` at the root covers it, and the root scripts delegate to `app`'s own scripts.

`npm run dev` starts Vite with hot reload and runs the shell. The app lives in the system tray: left-click the icon to toggle the popup, or use the tray menu (Show versions, Quit). Launching it a second time shows the running instance's popup instead of adding a second icon. UI edits reload in place; Rust edits make `tauri dev` rebuild and restart the app. What has been verified on a real machine is recorded in [docs/app/native-observations.md](docs/app/native-observations.md).

`npm run build` produces an NSIS installer under `app/src-tauri/target/release/bundle/` for local testing only. Published installers are built by CI from a release tag (the release workflow arrives with the release tickets), never on a contributor's machine.

### Installer and SmartScreen

The `Installer` workflow builds the per-user NSIS installer on a clean Windows runner for every push to a `ticket/**` or `integration/**` branch, and uploads it with `SHA256SUMS.txt`. The installer and the Windows executables are **unsigned** in v1, so SmartScreen shows "Windows protected your PC": verify the SHA-256 checksum, then choose "More info" and "Run anyway". The installer needs no administrator rights. The steps, and the manual install proof, are in [docs/app/install-proof.md](docs/app/install-proof.md). (Updater metadata is signed separately; that arrives with the release tickets.)

## Commands

All work goes through root npm scripts. `lint` and `test` run every part; the `:core`, `:repo`, `:gen`, `:ui` and `:rust` variants run one part each.

| Script | What it does |
| --- | --- |
| `npm run cli -- <args>` | Run the `versionbar` CLI from the checkout |
| `npm run dev` | Run the tray app with hot reload |
| `npm run build` | Local test build of the installer (releases come from CI) |
| `npm test` | `test:core`: pytest, CLI tests over the fake system plus an install smoke test (`uv tool install` of `core/`, then run the installed command, including a live `list --json` that must find git, validate against the committed schema and never import Rich). `test:ui`: Vitest, the popup rendered with Tauri's IPC mock. `test:rust`: `cargo test` for the shell |
| `npm run gen` | Regenerate `schema/` (JSON Schemas and TS types) and the UI's product-name constant from their sources; see [schema/README.md](schema/README.md) |
| `npm run doctor` | Check that node, npm, uv, rustc and cargo meet the repo pins, using `versionbar check` live on this machine with your normal VersionBar config (an invalid config file is reported as such). Failures name the tool and print the fix; exits 1 if anything is unmet. It checks only the contributor toolchain, not the tray app or installers |
| `npm run lint` | `lint:core`: ruff check and format check, ty. `lint:repo`: taplo (check and format, including the built-in tool definitions against their schema), actionlint. `lint:gen`: fails if any generated file is stale. `lint:ui`: `tsc --noEmit`, ESLint (typescript-eslint, react-hooks), Prettier. `lint:rust`: rustfmt, clippy `-D warnings`, cargo-deny |

CI runs the core, repo and UI checks on Windows and Ubuntu and the Rust checks on Windows only (the shell ships only for Windows, and building Tauri on Linux needs extra system packages). It also checks that PR titles follow Conventional Commits.

## Tooling choices

Everything runs through `uv`, so one prerequisite covers Python and the non-Node linters:

- ruff and ty are dev dependencies of `core/` (`uv.lock`).
- taplo runs from PyPI (`uvx taplo==<pin>`). The npm `@taplo/cli` was rejected because under Node 24 on Windows it silently finds zero TOML files.
- actionlint runs from PyPI (`uvx --from actionlint-py==<pin> actionlint`), a third-party wrapper ([Mateusz-Grzelinski/actionlint-py](https://github.com/Mateusz-Grzelinski/actionlint-py)) that downloads the official rhysd/actionlint release binary.

## Updating pins

| Pin | Where |
| --- | --- |
| Python 3.14 | `core/.python-version` and `requires-python` in `core/pyproject.toml` |
| npm 11 / Node | `packageManager` and `engines.node` in `package.json`; Node in `.github/workflows/ci.yml` |
| Rust toolchain | `rust-toolchain.toml`: an exact stable release, so new clippy lints never break CI unannounced |
| Python dependencies | `core/pyproject.toml`, then `uv lock --project core` (commit `core/uv.lock`) |
| UI and Tauri CLI dependencies | exact versions in `app/package.json`, then `npm install` (commit `package-lock.json`) |
| Rust dependencies | `app/src-tauri/Cargo.toml`, then `cargo update` (commit `app/src-tauri/Cargo.lock`). Keep the `tauri` crate and `@tauri-apps/api`/`@tauri-apps/cli` on the same minor version |
| cargo-deny | `tool:` in `.github/workflows/ci.yml`; policy in `app/src-tauri/deny.toml` |
| taplo, actionlint | the `lint:repo` script in `package.json` |
| GitHub Actions | exact tags in `.github/workflows/ci.yml` |

The product name lives in `core/pyproject.toml` (package and command name), `productName` and the popup window `title` in `app/src-tauri/tauri.conf.json`, and `PRODUCT_NAME` in `app/src/product.ts`. The app version is `version` in `app/src-tauri/Cargo.toml` (Tauri reads it from there). `app/src-tauri/tests/product_identity.rs` fails if the app version differs from the core's, or if the window title or `PRODUCT_NAME` differs from `productName`, the canonical display name.

## Licence

MIT, copyright Michael Tahery. See [LICENSE](LICENSE).
