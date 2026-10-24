# Tray app: native behaviour observations

What the tray shell does on a real Windows machine, and what has not been checked yet. Tray
and window behaviour has no unit tests (see "Testing" in `AGENTS.md`), so this page is the
record. Tickets 27 and 31 extend it into the full real-machine acceptance checklist.

## Ticket 20 (2026-10-24)

Machine: Windows 11 Pro 10.0.26200, one 1920×1080 monitor at 100% scale, taskbar at the
bottom (work area 1920×1032). Checked with `npm run dev` and with a release build
(`tauri build --no-bundle`), reading the window state through Win32 calls.

### Verified

| Behaviour | Observation |
| --- | --- |
| Launch | One process starts, the tray icon is created, and the popup starts hidden. |
| Second launch | The second process exits with code 0. The running app's popup becomes visible and focused; no second process or icon remains. |
| Placement before the tray icon has reported any mouse event | The positioner does not know the icon's position yet, so the popup falls back to the bottom-right corner. Its window spans (1512,471) to (1908,1020): 12 px clear of the right edge and of the bottom taskbar, inside the work area. |
| Focus loss | Bringing another window to the front hides the popup. |
| Rendering | Popup draws the header "VersionBar v0.1.0" (the version comes from the shell over IPC, so the CSP allows IPC) and follows the dark system theme. Same result in the release build with embedded assets. |
| Hot reload | Editing `app/src/App.tsx` while `npm run dev` runs makes Vite push an `hmr update`. |

### By design, not exercised by hand

- **Alt+F4** on the popup is intercepted and only hides it; the window and the app stay alive.
- **Clicking the icon while the popup is open** closes it. Windows takes focus away first,
  which already hides the popup, then delivers the click; a click within 300 ms of that
  focus-loss hide is ignored so it does not reopen the popup.
- **Known limitation of that 300 ms window:** pressing and holding the icon for longer than
  300 ms before releasing reopens the popup on release, because the click arrives on
  button-up.

### Not yet checked

- Left-click toggling and placement anchored on the tray icon itself. The icon landed in the
  Windows 11 overflow area and could not be clicked automatically.
- Right-click menu (Show versions, Quit).
- Taskbar on the top, left or right edge.
- Multiple monitors, and mixed DPI scales where the popup could sit off-centre from the icon.
- Taskbar at the top of a monitor that is not the topmost one: the positioner flips the popup
  below the icon only when it would go above the virtual screen's top edge (y < 0), so on a
  lower monitor it may be placed above the icon and then pushed back into the work area.

### Deferred

- Recreating the popup if its webview dies (ADR-0009) is not built yet. Nothing destroys the
  popup window today (Alt+F4 only hides it), but a crashed webview is not recovered.
- Mica backdrop (M4).

## Rust: what and why (ticket 20)

The Rust part of the app now does four things, all of them app lifecycle (ADR-0006, ADR-0009):

- **Tray icon.** At start it puts an icon in the Windows notification area, with a menu
  offering "Show versions" (opens the popup) and "Quit" (exits). The menu does not depend
  on the popup's web page, so it keeps working if that page is broken.
- **Popup.** Left-click opens or closes a small borderless window above the icon. The
  official positioner plugin finds where the icon is. Rust then nudges the window so it
  stays inside the screen area the taskbar leaves free, because the plugin only keeps it on
  the monitor. Clicking elsewhere hides the popup; Alt+F4 also only hides it.
- **One copy only.** The official single-instance plugin makes a second launch exit at once
  and ask the running copy to show its popup, so there is never a second icon.
- **Locked-down web page.** The popup may ask Rust for exactly one thing, the app version.
  It cannot run programs. `tests/capabilities.rs` fails if anyone grants it more without
  updating the reviewed list, `deny.toml` bans the shell plugin, and
  `tests/product_identity.rs` keeps the app version equal to the core's and the display
  name the same in the Tauri config and the UI.

## Ticket 21 (2026-10-24)

Checked with `npm run dev` on the same machine: at launch the shell ran the bundled core from
the debug resource folder, uv created `%LOCALAPPDATA%\io.github.7ahery.versionbar\core-env`
(with the bytecode cache in `core-env\pycache`) and no file appeared in the bundled `core/`
folder. The same `uv run` invocation, run by hand against that folder, printed a
`schema_version` 1 scan in about a second once the environment existed.

Not yet checked by hand: the popup list itself in the running app (it is covered by the
mocked-IPC UI tests), Refresh from the popup, and a run from an installed build (ticket 23).

## Rust: what and why (ticket 21)

The Rust shell can now run a scan and hand the result to the popup. Bundling and the exact
invocation are described in `docs/app/bundled-core.md`.

- **Finding uv.** Before every scan it looks for `uv.exe` on PATH, then in `UV_INSTALL_DIR`,
  then in `%USERPROFILE%\.local\bin`. The last two cover an app started at login without the
  terminal's PATH. Folders given as relative or empty paths are skipped, because they would
  depend on whatever folder the app happened to start in. If uv is nowhere, it reports "uv
  missing" and runs nothing. It never installs uv.
- **Running the core.** It starts uv with one fixed command line (`run --frozen --no-dev
  --managed-python --project <bundled core> -- versionbar list --json`). The Python
  environment and Python's bytecode files go in the app data folder, never in the install
  folder. No console window flashes. If the scan takes longer than 30 seconds, it kills uv
  and everything uv started; the Windows tool that does this (taskkill) gets at most one
  second, so it can never hold up the scan. If Windows cannot say whether uv is still running, it also
  kills it and reports a failure with Windows' error, rather than calling it a timeout.
- **Ignoring stray uv and Python settings.** uv also reads settings from `UV_...`
  environment variables. The shell removes the ones that would make uv pick a different
  Python, project or environment, or install a different set of packages than the shipped
  lock file. It also removes the `PYTHON...` variables that would make the core's Python load
  code from other folders or run extra code at start (the full lists are in
  `docs/app/bundled-core.md`). Settings for mirrors, proxies, the download cache and offline
  mode are kept, because some users need them to download anything.
- **Leftover readers.** After uv exits or is killed, the shell waits at most one more second
  for its output. If some other program still holds the output open, the scan goes on and a
  small background reader is left waiting until that program lets go. The core accepts the
  same trade-off for the tools it runs.
- **Checking the result.** It accepts the output only if it is a JSON object whose
  `schema_version` is 1. It reads no other field and passes the text on unchanged.
  Anything else (start failure, timeout, nonzero exit with its error output, non-JSON,
  another version) is recorded as a failure with a reason, and the last good result stays.
- **Holding state.** It keeps the latest and the previous good result in memory, plus
  whether a scan is running and how the last one ended. A refresh while a scan runs is
  ignored, so two scans never run at once.
- **Talking to the popup.** Two new commands: `get_state` (read the state) and `refresh`
  (start a scan; takes no arguments). A `scan-updated` event carries the new state when a
  scan starts and ends. The popup gained exactly four permissions: those two commands plus
  listening and un-listening for events. `tests/capabilities.rs` lists them. It still cannot
  run programs or pass arguments to the core.
- **Why the two event permissions.** The usual rule is one permission per scoped command,
  and the two event permissions are not commands of ours. They are Tauri's built-in way for
  a page to receive messages the app sends it: "listen" lets the popup start receiving
  `scan-updated`, "unlisten" lets it stop when it closes. Without them the popup could only
  ask for the state again and again. They only let the popup hear messages; they do not let
  it send anything to Rust, run anything or change any state. The alternative, a command
  that waits until the next scan finishes, would be a home-made copy of the same mechanism.
- **Order on the popup side.** The popup starts listening first and asks for the state only
  once listening works. Asking first could leave it showing "Scanning…" forever, if the scan
  finished in the moment between the answer and the start of listening.
- **Startup.** One scan starts at launch, so the popup has data by the time it opens.
- **Dependencies.** `serde` and `serde_json` became direct dependencies. They were already
  built as part of Tauri, so nothing new is downloaded. `serde_json` gained its `raw_value`
  feature, which keeps scan results as untouched text.
