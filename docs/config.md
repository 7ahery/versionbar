# User config

One TOML file, shared by the CLI and the tray app. The core reads it live on every `list`, `show`, `check` and `config` run (the core never caches), so an edit applies to the next scan. Without the file every default applies. The model is `ConfigFile` in `core/src/versionbar/config.py`; unknown keys are rejected.

## Where it is

`config.toml` in the platform's per-user config folder, from platformdirs (`user_config_dir`, roaming, no app-author folder):

| OS | Path |
|---|---|
| Windows | `%APPDATA%\versionbar\config.toml` |
| Linux | `$XDG_CONFIG_HOME/versionbar/config.toml`, by default `~/.config/versionbar/config.toml` |

The folder name is the package name. `versionbar config` prints the resolved path. Nothing creates the file: the CLI never writes it, and the app creates it only from the starter template (below).

## Keys

```toml
timeout = 8                 # seconds per version command (default 5)
pinned = ["node", "git"]    # shown first, in this order
order = ["python"]          # shown after the pinned ones, in this order
hidden = ["uv"]             # left out of `list`

[timeouts]                  # per tool, wins over `timeout`
git = 10

[app]
update_check = false        # the app never checks for updates (default true)

[[tools]]                   # a custom tool: same keys as a built-in definition
id = "ssh"
name = "OpenSSH"
os = ["windows"]
binaries = ["ssh"]
version_args = ["-V"]
version_regex = 'OpenSSH_(?:for_Windows_)?(?P<version>\d+(?:\.\d+)*[a-z]*\d*)'
```

| Key | Type | Meaning |
|---|---|---|
| `timeout` | number > 0, finite | Seconds each version command may run before its tool is `timeout`. Default 5. |
| `timeouts.<id>` | number > 0, finite | That tool's timeout. Precedence: `timeouts.<id>`, then `timeout`, then 5. |
| `pinned` | list of ids | Listed first, in this order. |
| `order` | list of ids | Listed after the pinned tools, in this order. |
| `hidden` | list of ids | Left out of `list`. |
| `app.update_check` | boolean | Whether the tray app checks for updates. Default true. The CLI ignores it. |
| `tools` | array of tables | Custom tool definitions; every key of [docs/definitions.md](definitions.md) (`via`, `overrides` included), validated exactly like a built-in. |

Values are typed strictly: `timeout = "5"` or `update_check = 1` is an error, not coerced.

### Tool ids

- Every id in `pinned`, `order`, `hidden` and `timeouts` must be a known tool (built-in or custom) on some OS. A tool of another OS is allowed, so one file can serve several machines; it is simply not listed here.
- An id appears at most once across `pinned`, `order` and `hidden` together.
- Two custom tools may not share an id.
- A custom tool with a built-in's id **replaces** that built-in, in the built-in's place in the default order. So a built-in added in a later release never breaks a config that already defined that tool.

### Order of `list`

1. Pinned tools, in `pinned` order.
2. Ordered tools, in `order` order.
3. Every other tool in default order: the built-ins by file name (`git`, `node`, `python`, `uv`, …), then custom tools in file order.

Hidden tools are left out. `show` and `check` are unaffected: they report the tools asked for, in request order, hidden ones included. A requirement on a hidden tool is checked like any other, never dropped. The order applies to the human table and to the `tools` array of `list --json` alike. The tray app does its own sorting from the same `pinned` and `order` lists (ticket 26).

## Invalid config

A file that cannot be used stops `list`, `show` and `check` with **exit code 3** before anything is scanned. stderr names the file, then one line per problem: the key (dotted, with list indexes) and what is wrong. Nothing is printed on stdout, with or without `--json`.

```
invalid config file C:\Users\me\AppData\Roaming\versionbar\config.toml
  pinned[1]: unknown tool "nod"
  tools[0].version_regex: version_regex needs a named group `(?P<version>...)`
  timeout: Input should be greater than 0
```

A problem with the whole file has no key: it cannot be read (`cannot read it: …`), is not UTF-8 (a BOM is accepted), or is not valid TOML (the message gives line and column). A missing file is not a problem. All problems found are reported at once; the cross-references (unknown ids, duplicates) are checked only once the file's types are valid.

Exit codes: 0 success, 1 `check` requirement failed (or `debug capture` failed), 2 usage error, 3 invalid config.

## `versionbar config`: the preferences query

`versionbar config` shows the file's path and every setting in effect, or every problem. It runs no tool. `versionbar config --json` prints a `ConfigResult` (schema in `schema/output.schema.json`, TS type in `schema/output.d.ts`):

```json
{
  "schema_version": 1,
  "config_path": "C:\\Users\\me\\AppData\\Roaming\\versionbar\\config.toml",
  "config_exists": true,
  "problems": [],
  "preferences": { "update_check": false, "pinned": ["node", "git"], "order": ["python"] }
}
```

- Exit 0 when the config is usable (including absent). Exit 3 when not: the document is still printed, with every problem in `problems` (`key` null for whole-file problems) and `preferences` null. `config_path` is always there, so the app can still open the file to fix it.
- This is the app's second and last fixed core invocation (ADR 0011). The app reads `config_path` (Open config file), `preferences.update_check` (the updater) and `pinned`/`order` (sorting). Fields are added under the [compatibility rules](../schema/README.md); consumers ignore unknown ones.
- When `preferences` is null the app does not know the update preference. It must not treat that as "enabled": keep the last known value, and without one, do not check (12b, 30).

## Starter template

`core/src/versionbar/starter_config.toml` is the one starter config. It ships as a package resource (in the wheel, and in the app's bundled core at `<resource_dir>/core/src/versionbar/starter_config.toml`). Lines starting `##` explain; lines starting `# ` are disabled examples. As shipped it sets nothing, and with every `# ` removed every example is valid; core tests check both.

Ticket 27's Open config file, when `config_path` does not exist, copies this file byte for byte to `config_path` with a create-only write (fail if it exists, never overwrite), creating the folder, and then opens it. Rust keeps no second template and never parses or edits TOML.

## For ticket 16 (`tools` catalog)

`load_settings(system, builtins)` in `core/src/versionbar/config.py` returns `Settings`; `Settings.registry` is the validated `Registry`: `definitions` (every tool on every OS, built-ins first, custom tools merged by the replacement rule above) and `custom_ids` (ids defined by the config). The catalog lists from it rather than from the built-ins alone.
