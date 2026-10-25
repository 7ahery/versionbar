# Preferences: how the app learns what the config file sets

The tray app never reads the config file. It asks the core with the second of its two fixed
invocations, `versionbar config --json` ([ADR 0011](../adr/0011-preferences-query.md)), and
hands the answer to whoever needs it. This page is the transport contract for the popup's
pinning and ordering (ticket 26), the native "Open config file" action (ticket 27) and the
updater (ticket 30). Code: `app/src-tauri/src/preferences.rs`; the invocation itself is shared
with the scan in `app/src-tauri/src/scan.rs`. The config file's keys are in
[../config.md](../config.md).

## The invocation

```
uv run --frozen --no-dev --managed-python --project <resources>\core -- versionbar config --json
```

Everything except the last two arguments is the scan's invocation: the same uv lookup,
environment variables, project environment, timeout, kill-on-timeout and stderr capture
([bundled-core.md](bundled-core.md#the-two-invocations)). The arguments are fixed; nothing the
webview sends can change them.

## When it runs

Every scan job runs the query first, then the scan, one after the other on the same thread.
So the preferences are reread on every refresh, whatever started it:

- at launch, before the first scan, so the update setting is known as early as possible;
- from the popup (`refresh`), and after editing the config file, which is how a config change
  is reloaded;
- from the tray menu's Refresh, which needs no webview;
- every 30 minutes with the scheduled scan.

A refresh requested while a job runs queues one follow-up job exactly as for scans
([state.md](state.md#when-it-refreshes)), and that job rereads the preferences too. The query
and the scan never run at the same time, so there is never more than one uv process. On a
first run (no `core-env` yet) the query gets the first-run timeout, because it may be the
invocation that builds the environment.

## What Rust reads

The answer is a `ConfigResult` (generated in `schema/output.d.ts`). Rust holds it as opaque
JSON and passes it to the popup unchanged. It checks `schema_version` like a scan result and
reads exactly two fields beyond that:

| Field | Used for |
|---|---|
| `config_path` | The file "Open config file" opens (ticket 27), whether or not it exists. |
| `preferences.update_check` | Whether the updater may go online (ticket 30). |

This is a deliberate, narrow exception to hard rule 2 ("Rust treats scan JSON as opaque"),
accepted with ADR 0011 (DEC-13): these two values steer Rust's own behaviour, which the UI
cannot do for it, and they come from the core's resolution of the config, so Rust still never
parses TOML or duplicates config logic. Everything else (`config_exists`, `problems`, `pinned`,
`order`) is for the popup only. Do not read further fields in Rust; add a field to this table
only with a new decision.

Rust-side accessors (on `Preferences`, held in Tauri state as `Arc<Preferences>`):

- `update_check() -> bool`: the update decision. See the fail-safe below.
- `config_path() -> Option<PathBuf>`: the path from the latest answer; `None` until a query
  has answered.

## How each ending is handled

| How the query ends | `config` (to the popup) | `outcome` | `update_check()` |
|---|---|---|---|
| Exit 0, valid answer | the new answer | `ok` | the answer's `preferences.update_check` |
| Exit 3 (invalid config) with a valid answer | the new answer: `config_path` and `problems`, `preferences` null | `ok` | unchanged |
| uv not found | unchanged | `uv_missing` | unchanged |
| uv cannot start | unchanged | `failed`, reason `launch` | unchanged |
| No exit within the timeout | unchanged | `failed`, reason `timeout` | unchanged |
| Any other exit code, or exit 3 without a valid answer | unchanged | `failed`, reason `exit`, with stderr | unchanged |
| Exit 0 but not a JSON object, or no `preferences.update_check` boolean | unchanged | `failed`, reason `malformed` | unchanged |
| A `schema_version` other than the supported one | unchanged | `failed`, reason `incompatible` | unchanged |

"Unchanged" means the last value since launch. A valid answer counts even with exit 3: the
popup needs its path and problems so the user can open and fix the file.

### The update-flag fail-safe

`update_check()` is the last `update_check` a usable config gave since the app started. If the
query fails, times out, prints garbage or reports an invalid config, that last value stays.
If no usable answer has arrived since launch, updates are treated as **disabled**. An unknown
setting never means "enabled" (ADR 0011), so a user who turned update checks off is never
checked for updates because their file broke or uv went missing. The value is not saved
between launches: the launch job's query decides it afresh.

The updater (ticket 30) must therefore read `update_check()` only after the launch job's query
has finished, for example on the first `preferences-updated` notification, and must treat a
`false` before then as "not yet allowed", not as a final answer.

## IPC contract with the popup

| Name | Kind | Payload |
|---|---|---|
| `get_preferences` | command | no arguments; returns the state below |
| `preferences-updated` | event, Rust to webview | the state below, sent after every query (also failed ones) |

Permission: `allow-get-preferences` in `app/src-tauri/capabilities/default.json`. There is no
command to run the query on its own: `refresh` reruns it.

```ts
{
  config: ConfigResult | null;  // latest answer as printed by the core, including one for an
                                // invalid config; null until a query has answered
  outcome: null                 // no query has finished in this session yet
    | { kind: "ok" }
    | { kind: "uv_missing" }
    | { kind: "failed"; reason: string; message: string; stderr: string };
}
```

`outcome` uses the same shape and reasons as the scan's ([bundled-core.md](bundled-core.md#ipc-contract-with-the-popup)).
`config.preferences` is null when the config is invalid; `config.problems` then says why.

As with the scan state, a consumer subscribes to `preferences-updated` first and calls
`get_preferences` only once the subscription is in place, and ignores a `get_preferences`
answer that arrives after an event. Consumers must handle unknown `kind` and `reason` values.

## Timeouts in the config file

The app gives each scan a fixed 30 seconds (180 on a first run). The config file's `timeout`
and `timeouts.<id>` keys set how long the core waits for each tool's version command. A single
tool timeout close to or above about 30 seconds can make the whole scan hit the app's limit,
and so can several long ones, since the core runs only a few commands at a time. The scan then
fails with reason `timeout` and the app keeps the last good results. The app does not raise its limit to match; keep per-tool timeouts well below 30
seconds when using the tray app.
