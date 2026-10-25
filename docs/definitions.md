# Writing tool definitions

A tool is one TOML file in `core/src/versionbar/definitions/`, checked against `schema/definition.schema.json` (taplo, editors) and by the loader (`ToolDefinition` in `core/src/versionbar/definition.py`). The engine has no per-tool code: anything a tool needs is expressed with the keys below. Unknown keys are rejected.

```toml
#:schema ../../../../schema/definition.schema.json
id = "python"
name = "Python"
os = ["windows", "linux"]
binaries = ["python", "python3"]
version_args = ["--version"]
version_regex = 'Python (?P<version>\d+\.\d+\.\d+\S*)'

[[via]]
manager = "pyenv"
dirs = ["{PYENV_ROOT}/shims", "{HOME}/.pyenv/shims"]

[[overrides.windows.via]]
manager = "pyenv"
dirs = ["{PYENV}/shims", "{PYENV_ROOT}/shims"]
```

| Key | Meaning |
|---|---|
| `id`, `name`, `os` | Stable id, display name, OSes it is detected on. |
| `binaries` | Command names looked up on PATH, in order. PATHEXT applies on Windows. |
| `version_args` | Arguments that print the version. |
| `version_regex` | Python regex with a named group `(?P<version>...)`, searched in stdout then stderr. |
| `via` | Shim rules, see below. Default: none. |
| `overrides.<os>` | Replaces `binaries`, `version_args`, `version_regex` or `via` (the whole list) on that OS. |

## Installs come from PATH

Every runnable PATH hit is an install with `source = "path"`, the first one active. Store placeholders are never run, duplicate PATH entries collapse, relative PATH entries are skipped, and an extensionless file is never a Windows hit. Installs that are not on PATH (nvm's Node versions, uv's Pythons, rustup toolchains) come from [providers](providers.md), never from a definition.

## Windows wrappers (`.cmd`, `.bat`)

Nothing to declare. `binaries = ["npm"]` resolves to `npm.cmd` through PATHEXT, skipping the extensionless `npm` script beside it, exactly as `cmd.exe` would. The install's path is the wrapper's own path, since that is what typing the command runs.

The runner starts wrappers through `%SYSTEMROOT%\System32\cmd.exe /d /e:on /v:off /s /c`: AutoRun hooks are skipped, command extensions are on and delayed expansion off. So `version_args` for a tool that may resolve to a wrapper must avoid characters `cmd.exe` would reinterpret: whitespace, `% " ^ & | < > ( ) ! , ; =`. A wrapper given such an argument (or an empty one), or whose path contains `%` or `"`, is not run and the install reports an error saying so. Plain flags (`--version`, `version`, `-v`, `--client`) are fine.

## Shim attribution (`via`)

`[[via]]` rules are tried in order for every install on PATH; the first that matches sets the install's `via` to its `manager`. `manager` is a free string, but built-in definitions use only the spec's managers (`corepack`, `volta`, `pyenv`) plus `nvm`, unless spec #1 changes. When a provider also reports that manager's installs, `manager` must be the provider's id: a PATH install with that `via` is then the shim serving one of the provider's installs, and the provider's install of the same version is not listed a second time ([docs/providers.md](providers.md)). Node's built-in rule does this for nvm-windows: `manager = "nvm"`, `dirs = ["{NVM_HOME}/.nodejs", "{NVM_SYMLINK}"]`. A rule matches when every condition it gives matches, and it must give at least one:

- `dirs`: the install's folder is one of these folders. Each starts with an environment variable, `{NAME}`, and may use more: `{VOLTA_HOME}/bin`. Use `/`; it becomes `\` on Windows, and comparison follows the OS (case-insensitive on Windows). A folder whose variable is unset or empty, or that is not absolute once expanded, is ignored. There are no fixed paths: a manager is recognised wherever its variable says it lives, and a folder that only looks like a manager's default is not tagged. List fallbacks as extra folders (`{PYENV_ROOT}/shims`, `{HOME}/.pyenv/shims`); all of them count. Variables must hold one folder, not a list.
- `content_regex`: a Python regex searched for in the first 16 KiB of the install's file, decoded as UTF-8. For shims recognisable only by what their manager writes into them. The file is read, never run; an unreadable file does not match.

Attribution never changes which install is active or what is run: `via` only explains why that install is there.

## How the ecosystem tickets use this

| Ticket | Case | Expressed as |
|---|---|---|
| 09 (#12) pyenv | pyenv-win shims (`python.bat`) | `[[overrides.windows.via]] manager = "pyenv"`, `dirs = ["{PYENV}/shims", "{PYENV_ROOT}/shims", "{PYENV_HOME}/shims"]` |
| 09 | pyenv on Linux | `[[via]] manager = "pyenv"`, `dirs = ["{PYENV_ROOT}/shims", "{HOME}/.pyenv/shims"]` |
| 09 | pip, pipx, poetry | Plain definitions; the same pyenv rule where pyenv shims them. |
| 13 (#15) volta | `node`, `npm` served by Volta (pnpm and yarn are dropped from v1, DEV-6) | `[[via]] manager = "volta"`, `dirs = ["{VOLTA_HOME}/bin"]` (plus a Windows fallback such as `{LOCALAPPDATA}/Volta/bin` if captures show `VOLTA_HOME` can be unset). Not added yet: needs a real volta capture. |
| 13 | corepack's `pnpm`/`yarn` | Dropped from v1 (DEV-6): no corepack attribution and no probe-environment work. |
| 13 | `npm.cmd` | Nothing: wrappers resolve and run as above. |
| 13 | nvm, fnm, volta themselves | Plain definitions; their binaries are on PATH. nvm-held Node versions are the nvm provider's ([docs/providers.md](providers.md)); node's `[[via]]` rule for nvm is already built in, so add other rules to the same list. |
| 14 (#16) | java, go, rustc, cargo, rustup, dotnet, ruby, php, composer | Plain definitions (`composer.bat` is a wrapper). A `via` rule only where a manager shims the tool, such as `{CARGO_HOME}/bin` for rustup's proxies if that attribution is wanted. |
| 15 (#17) | `code` → `code.cmd` | Nothing: the extensionless `code` script is skipped and `code.cmd` runs as a wrapper. |
| 15 | scoop, choco, winget | Plain definitions; scoop's shims could use `dirs = ["{SCOOP}/shims"]` if attribution is wanted (needs a spec change: `via` values are `corepack`, `volta`, `pyenv`). |

### Language toolchains (ticket 14): coverage and provenance

Built-in definitions: `java`, `go`, `rustc`, `cargo`, `rustup`, `dotnet`, `ruby`, `php`, `composer`, all plain (no `via`), all Windows and Linux. They only see installs on PATH; rustup toolchains and extra .NET SDKs are for later providers.

Fixtures are real Windows captures. `rustc`, `cargo` and `rustup` come from the maintainer's machine (`%USERPROFILE%\.cargo\bin`). `java` (Temurin 17), `go`, `dotnet`, `ruby`, `php` and `composer` come from the `windows-latest` runner via the capture workflow. Notable real output: `java -version` prints to stderr only, so the engine's per-stream search matters; `composer` is `composer.bat` and prints a PHP notice on stderr; `rustup` prints `info:` lines on stderr. No Linux captures exist yet, so Linux behaviour of these definitions is unverified.

Not supported by definitions, by design:

- Installs found only through an environment variable and not on PATH (`JAVA_HOME` without java on PATH, a manager binary off PATH). They are not what typing the command runs and need a `source` other than `path`, which is provider territory ([docs/providers.md](providers.md)).

### Hosting, shell and platform tools (ticket 15): coverage and provenance

Built-in definitions shipped: `gh`, `pwsh`, `code` (Windows and Linux) and `wsl`, `winget` (Windows only). Fixtures are real Windows captures from the maintainer's machine (`wsl` included: its UTF-16 output is decoded from the raw bytes, with no `encoding` key in the definition). `code` resolved to `code.cmd`, so it runs as a wrapper through the shared cmd.exe path. `docker`, `kubectl`, `scoop` and `choco` are not on that machine; they need a capture from the `capture.yml` workflow before their definitions ship.

### Coverage checklist

The v1 catalog is 32 tools: spec #1's 34 minus `pnpm` and `yarn` (DEV-6). Status is "shipped" when a definition and a real capture exist.

| Group | Tool | Definition | Real capture |
|---|---|---|---|
| VCS / hosting | git | shipped | yes |
| | gh | shipped (15) | yes |
| Python | python, uv | shipped | yes |
| | pip, pipx, poetry | ticket 09 | pending |
| JS | node, npm | shipped (13) | yes |
| | bun, deno | ticket 13 | pending |
| PHP | php, composer | shipped (14) | yes |
| Other languages | java, go, rustc, cargo, dotnet, ruby | shipped (14) | yes |
| Containers | docker, kubectl | pending (15) | blocked: not on the maintainer's machine |
| Managers | nvm | shipped (13) | yes |
| | fnm, volta, pyenv | tickets 09 and 13 | pending |
| | rustup | shipped (14) | yes |
| | winget | shipped (15) | yes |
| | scoop, choco | pending (15) | blocked: not on the maintainer's machine |
| Dev shell | pwsh, code, wsl | shipped (15) | yes |
- Setting environment variables for the version command. That was only needed for corepack shims, and pnpm, yarn and so corepack are dropped from v1 (DEV-6), so no probe-environment key exists. Revisit if they return.

### JS tools and managers (ticket 13)

Built-in so far: `npm` and `nvm`, with real Windows captures from the maintainer's machine (npm 11.19.0 under nvm's `.nodejs` folder, nvm-windows 2.0.1). `bun`, `deno`, `fnm` and `volta` (with volta attribution for node/npm) are pending real captures: none is installed on the capture machine and the capture workflow cannot take an unmerged definition without a pushed branch. A manager's own version detection is a tool, not a provider; only nvm has a provider ([docs/providers.md](providers.md)).
