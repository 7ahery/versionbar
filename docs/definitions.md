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

Every runnable PATH hit is an install with `source = "path"`, the first one active. Store placeholders are never run, duplicate PATH entries collapse, relative PATH entries are skipped, and an extensionless file is never a Windows hit. Installs that are not on PATH (nvm's Node versions, uv's Pythons, rustup toolchains) come from providers (ticket 16), never from a definition.

## Windows wrappers (`.cmd`, `.bat`)

Nothing to declare. `binaries = ["npm"]` resolves to `npm.cmd` through PATHEXT, skipping the extensionless `npm` script beside it, exactly as `cmd.exe` would. The install's path is the wrapper's own path, since that is what typing the command runs.

The runner starts wrappers through `%SYSTEMROOT%\System32\cmd.exe /d /e:on /v:off /s /c`: AutoRun hooks are skipped, command extensions are on and delayed expansion off. So `version_args` for a tool that may resolve to a wrapper must avoid characters `cmd.exe` would reinterpret: whitespace, `% " ^ & | < > ( ) !`. A wrapper given such an argument (or an empty one), or whose path contains `%`, is not run and the install reports an error saying so. Plain flags (`--version`, `version`, `-v`, `--client`) are fine.

## Shim attribution (`via`)

`[[via]]` rules are tried in order for every install on PATH; the first that matches sets the install's `via` to its `manager`. A rule matches when every condition it gives matches, and it must give at least one:

- `dirs`: the install's folder is one of these folders. Each starts with an environment variable, `{NAME}`, and may use more: `{VOLTA_HOME}/bin`. Use `/`; it becomes `\` on Windows, and comparison follows the OS (case-insensitive on Windows). A folder whose variable is unset or empty, or that is not absolute once expanded, is ignored. There are no fixed paths: a manager is recognised wherever its variable says it lives, and a folder that only looks like a manager's default is not tagged. List fallbacks as extra folders (`{PYENV_ROOT}/shims`, `{HOME}/.pyenv/shims`); all of them count. Variables must hold one folder, not a list.
- `content_regex`: a Python regex searched for in the first 16 KiB of the install's file, decoded as UTF-8. For shims recognisable only by what their manager writes into them. The file is read, never run; an unreadable file does not match.

Attribution never changes which install is active or what is run: `via` only explains why that install is there.

## How the ecosystem tickets use this

| Ticket | Case | Expressed as |
|---|---|---|
| 09 (#12) pyenv | pyenv-win shims (`python.bat`) | `[[overrides.windows.via]] manager = "pyenv"`, `dirs = ["{PYENV}/shims", "{PYENV_ROOT}/shims", "{PYENV_HOME}/shims"]` |
| 09 | pyenv on Linux | `[[via]] manager = "pyenv"`, `dirs = ["{PYENV_ROOT}/shims", "{HOME}/.pyenv/shims"]` |
| 09 | pip, pipx, poetry | Plain definitions; the same pyenv rule where pyenv shims them. |
| 13 (#15) volta | `node`, `npm`, `pnpm`, `yarn` served by Volta | `[[via]] manager = "volta"`, `dirs = ["{VOLTA_HOME}/bin"]` (plus a Windows fallback such as `{LOCALAPPDATA}/Volta/bin` if captures show `VOLTA_HOME` can be unset) |
| 13 | corepack's `pnpm`/`yarn` | `[[via]] manager = "corepack"` with a `content_regex` matching the corepack path the shim launches (`corepack[\\/]dist[\\/]` on Windows `.cmd` shims; on Linux the file is a symlink whose target, read through it, also names corepack). Take the exact marker from a real shim. |
| 13 | `npm.cmd`, `pnpm.cmd`, `yarn.cmd` | Nothing: wrappers resolve and run as above. |
| 13 | nvm, fnm, volta themselves | Plain definitions; their binaries are on PATH. nvm-held Node versions are the nvm provider's (ticket 16). |
| 14 (#16) | java, go, rustc, cargo, rustup, dotnet, ruby, php, composer | Plain definitions (`composer.bat` is a wrapper). A `via` rule only where a manager shims the tool, such as `{CARGO_HOME}/bin` for rustup's proxies if that attribution is wanted. |
| 15 (#17) | `code` → `code.cmd` | Nothing: the extensionless `code` script is skipped and `code.cmd` runs as a wrapper. |
| 15 | scoop, choco, winget | Plain definitions; scoop's shims could use `dirs = ["{SCOOP}/shims"]` if attribution is wanted (needs a spec change: `via` values are `corepack`, `volta`, `pyenv`). |

Not supported by definitions, by design:

- Installs found only through an environment variable and not on PATH (`JAVA_HOME` without java on PATH, a manager binary off PATH). They are not what typing the command runs and need a `source` other than `path`, which is provider territory (ticket 16).
- Setting environment variables for the version command. Corepack shims may download a package manager or pin one into a `package.json` in the current folder when run; if ticket 13 finds that `--version` does either on real machines, the generic fix is a definition key for the probe's environment (for example `COREPACK_ENABLE_NETWORK=0`), which needs a change to the System seam's `run`.
