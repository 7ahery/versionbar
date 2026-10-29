# App updates

The Rust shell checks for new VersionBar releases and installs one only after the user confirms
it in the popup (spec stories 34 and 69-71, ticket 30). Code: `app/src-tauri/src/update.rs`
(schedule, state, the plugin adapter) and `app/src/UpdateBanner.tsx` (the banner). How releases,
the feed and its signature are produced is in [install-proof.md](install-proof.md).

## What goes online, and when

- The only request is the feed, `https://github.com/7ahery/versionbar/releases/latest/download/latest.json`
  (`plugins.updater.endpoints` in `app/src-tauri/tauri.conf.json`), followed by the installer
  download after the user confirms. Nothing else is fetched (AGENTS.md hard rule 10).
- A check runs only while the latest preferences say `update_check` is on
  ([preferences.md](preferences.md#the-update-flag-fail-safe)). Until the launch job's first
  preferences query has answered, the setting counts as off, so the startup check waits for it.
  With update checks off, the feed is never requested.
- Checks run once the setting is known at launch and then every 24 hours while the app runs
  (`CHECK_INTERVAL`). The schedule looks again after every preferences query (every scan job,
  so at least every 30 minutes) and at least hourly; the feed is asked only when 24 hours have
  passed since the last check.
- A config change applies without restart: the next refresh rereads the preferences. Turning
  checks off stops requests and hides an offer already shown. Turning them back on shows an
  offer the app had already found again at once, with no new request, and otherwise keeps the
  24-hour schedule from the last check.
- An answer that arrives after checks were turned off is not shown.
- Each feed request times out after 30 seconds (`CHECK_TIMEOUT`) and the installer download
  after 15 minutes (`DOWNLOAD_TIMEOUT`), so a stalled request ends as a failure. No lock is
  held while a request runs, so a slow check never holds up a confirmed install.
- The release on `releases/latest` is never a prerelease, so installed apps are only offered
  full releases.

## Failures

| What failed | What the user sees | Then |
|---|---|---|
| A check: offline, DNS, a malformed feed, or the 404 the feed returns while a release builds or after a failed release run | Nothing. An offer from an earlier check stays. | The next scheduled check, 24 hours later (DEV-10). |
| After the user confirmed: download, signature verification, starting the installer | The banner shows the error and a Retry button; the offer stays. | Retry tries the same release again. |

The Tauri updater counts every answer but a 204 or a valid feed as an error, which is why failed
checks are quiet: every release has a window in which the feed is missing. The scan state, the
saved results and the preferences are never touched by an update or its failure.

The plugin verifies the downloaded installer against the public key in
`plugins.updater.pubkey` before running it; a download that fails verification is never run.
The installer itself is unsigned in v1 (see [install-proof.md](install-proof.md)).

## Installing

The user clicks `Update to v<version> → Install & restart`. The popup calls `install_update`;
Rust downloads the installer the last check offered, verifies it and starts it in passive mode
(a progress window, no questions). On Windows the app exits as the installer starts, and the
installer starts the new version when it is done. App and bundled core share one version and
one installer, so both are replaced together.

The core's environment in the app data folder survives the update. The first scan after the
app version changes runs as a first run (180-second timeout, `setting_up`) because
`uv run --frozen` re-syncs the environment to the new lock file and may download packages or a
new Python. The shell recognises it from `core-env-version.txt`, next to `core-env`, which holds
the app version of the last successful scan. A missing file counts as a different version.
See [bundled-core.md](bundled-core.md#where-things-are-written).

## IPC contract with the popup

| Name | Kind | Payload |
|---|---|---|
| `get_update` | command | no arguments; returns the state below |
| `install_update` | command | no arguments, returns nothing; installs whatever the last check offered, or does nothing without an offer. Progress and failures arrive as `update-updated` |
| `update-updated` | event, Rust to webview | the state below, sent whenever it changes |

Permissions: `allow-get-update` and `allow-install-update` in
`app/src-tauri/capabilities/default.json`. The webview holds no `updater:*` permission, so it
cannot check, download or install on its own (`tests/capabilities.rs`).

```ts
{
  version: string | null;  // the newer version on offer; null when none, or checks are off
  installing: boolean;     // from the confirmation until the install fails or the app restarts
  error: string | null;    // why the last confirmed install failed, a sentence for the user
}
```

As with the scan state, a consumer subscribes to `update-updated` first and calls `get_update`
only once the subscription is in place, and ignores a `get_update` answer that arrives after an
event. The TS mirror is `UpdateState` in `app/src/shell.ts`.
