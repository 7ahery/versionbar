# VersionBar

Inventories the dev tools installed on a machine. The `versionbar` CLI (Python core) is the product; a Windows tray app will be one consumer of it.

**Status: scaffolding.** The CLI installs and prints `--help`, but no tool detector exists yet.

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
| `npm test` | pytest, including an install smoke test (`uv tool install` of `core/`, then run the installed command) |
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
