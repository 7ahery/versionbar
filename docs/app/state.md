# Scan state: who owns it, where it is saved, when it refreshes

The Rust shell owns the scan state (spec "State ownership"); the core never caches (AGENTS.md
hard rule 6) and the popup only displays what the shell sends it. The state, the IPC commands
and the `scan-updated` event are described in [bundled-core.md](bundled-core.md#ipc-contract-with-the-popup).
Code: `app/src-tauri/src/scan.rs` (state and refreshing) and `app/src-tauri/src/saved.rs` (the
file).

## Who owns what

| Part | Owns |
|---|---|
| Core | One live scan per invocation. Rereads the config file every time, so config edits apply on the next refresh (spec story 58). Keeps nothing between runs. |
| Rust shell | The current and previous successful results as opaque text, whether a scan is running, the last outcome, the saved file and the refresh schedule. Reads only `schema_version`. |
| Popup | Everything a result means: age (from `scanned_at`), the list, diffing, sorting. Holds no state of its own beyond the last `ShellState` it received. |

## The saved file

`%LOCALAPPDATA%\io.github.7ahery.versionbar\scan-state.json`, next to `core-env`. Local, not
roaming: a scan describes one machine.

```json
{"format": 1, "current": <scan result>, "previous": <scan result or null>}
```

- `format` is the layout of this file and changes only if the wrapper does. It is unrelated to
  the scans' `schema_version`.
- `current` and `previous` are the core's output exactly as printed.
- Written after every successful scan, before the new state is announced. Failed scans leave
  the file alone, so it always holds the last successful pair.
- Written to `scan-state.json.tmp` first, flushed to disk and renamed over the real file. An
  interrupted write leaves the old file intact; the leftover `.tmp` is never read and is
  overwritten by the next save.
- If the file cannot be written (disk full, folder not writable) the scan still succeeds and
  the results stay in memory; the next successful scan tries again.

At launch the shell loads the file before anything else. It is ignored as a whole, and the app
starts with no results, when it is missing, is not valid JSON, has another `format`, or holds a
scan that is not a JSON object with the supported `schema_version` (for example one saved by a
newer version before a downgrade). Nothing deeper is read, and the next successful scan
replaces the file.

Restored results come back as `current` and `previous` with `outcome: null`, because nothing
has finished in this session yet. Because there is a `current`, the popup shows the list (with
its age) rather than a recovery or setup screen, even while a one-time setup runs. The
first-run rules (180-second timeout, `setting_up`) depend only on `core-env`, never on saved
results.

## When it refreshes

- **At launch**, straight after loading the file, so restored results are soon replaced.
- **Every 30 minutes**, counted from the end of the previous scheduled scan
  (`REFRESH_INTERVAL`). Not configurable yet.
- **From the popup** (`refresh` command) and **from the tray menu's Refresh**. The menu item
  talks to the scanner directly, so it works before the popup has ever loaded and while its
  page is broken (spec story 57).

All of these go through the same rule: scans never overlap. A request made while a scan runs
does not start a second core process. Instead the running scan is followed by exactly one more
scan when it ends, because the request may come after a config edit that the running scan
missed. Any number of requests during one scan share that one extra scan. The popup sees one
continuous scan: the first result is announced with `scanning` still true.
