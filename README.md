# VersionBar

Inventories the dev tools installed on a machine. The `versionbar` CLI (Python core) is the product; a Windows tray app will be one consumer of it.

**Status: early M1.** The CLI detects one tool (git) live. More tools, `check`, `tools` and `schema` arrive in later slices.

## Usage

```sh
versionbar               # same as `versionbar list`
versionbar list          # table: each tool's active version, path and count of other installs
versionbar show git ...  # every install of the given tools, the active one first (also: `--json`)
versionbar list --json   # machine-readable ScanResult (also: `versionbar --json`)
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
- `status` is one of `found`, `missing`, `error`, `timeout`. A missing tool is still listed, with `active: null` and no installs.
- `active` is the install that runs when you type the command: the first PATH hit, following PATHEXT on Windows (PATH order first, then PATHEXT order; extensionless files are never run). `installs` lists every install found, the active one included.
- Active versus other installs: the active install is the first hit, and it is also `installs[0]`. Every other entry in `installs` is an *other install*: a different file on PATH that the active one shadows. `list` shows how many (`len(installs) - 1`). A binary reached through several PATH entries (different case on Windows, trailing separators, `.`/`..`, quotes) counts once; genuinely different files, such as `git.exe` and `git.cmd` in one folder or two folders, stay separate. Symlinks are not resolved.
- An other install whose version command fails is left out of `installs` and explained in `notes`; if the active install fails, the tool's `status` is `error` or `timeout`.
- `versionbar show <tool>...` prints the same `ScanResult`, limited to the requested tools (in the order given, repeats dropped). An unknown id exits with code 2 and lists the known ids on stderr; nothing is written to stdout.
- `source` is `path` for installs found on PATH. `via` and `raw` are optional (`null` when absent); `raw` is the version output the version was read from.
- `notes` are human-readable diagnostics explaining a status (for example why a tool is missing, or the captured message of a failed version command). They are for people and logs, not for parsing.

## Tool definitions and fixtures

Built-in tools are TOML files in `core/src/versionbar/definitions/` (keys: `id`, `name`, `os`, `binaries`, `version_args`, `version_regex` with a named `version` group, and optional per-OS `overrides.<os>` replacing `binaries`, `version_args` or `version_regex`). The engine has no per-tool code.

Tests run the CLI over a fake system (`core/tests/fakes.py`) whose command output comes only from real captures in `core/tests/fixtures/<tool>/`. Each capture records its provenance (OS, resolved path, exact command, date) beside the output; see `docs/capture.md` to record one.

## Setup

Prerequisites: [uv](https://docs.astral.sh/uv/) and Node.js 24+ with npm 11. uv downloads the pinned Python (3.14) itself, so do not install a system Python. Windows contributors: see [docs/setup/windows.md](docs/setup/windows.md).

```sh
git clone https://github.com/7ahery/versionbar
cd versionbar
npm run cli -- --help     # first run creates core/.venv
```

Install the CLI from a checkout:

```sh
uv tool install ./core
versionbar --help
```

## Commands

All work goes through root npm scripts (there are no npm dependencies, so no `npm install` is needed):

| Script | What it does |
| --- | --- |
| `npm run cli -- <args>` | Run the `versionbar` CLI from the checkout |
| `npm test` | pytest: CLI tests over the fake system, plus an install smoke test (`uv tool install` of `core/`, then run the installed command, including a live `list --json` that must find git) |
| `npm run lint` | ruff check and format check, ty, taplo (check and format), actionlint |

More scripts (`dev`, `gen`, `doctor`, `build`) arrive with the slices that need them. CI runs `lint` and `test` on Windows and Ubuntu, and checks that PR titles follow Conventional Commits.

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
| Python dependencies | `core/pyproject.toml`, then `uv lock --project core` (commit `core/uv.lock`) |
| taplo, actionlint | the `lint` script in `package.json` |
| GitHub Actions | exact tags in `.github/workflows/ci.yml` |

The product name and version live only in `core/pyproject.toml`.

## Licence

MIT, copyright Michael Tahery. See [LICENSE](LICENSE).
