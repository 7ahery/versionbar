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

## Ticket 22 (2026-10-25)

Not run in the live tray: the tray badge was checked only by drawing the badged icon at
32x32 from `icons/32x32.png` and looking at it (an amber dot with a dark exclamation mark in
the bottom-right corner, with a thin white ring, legible on a dark background). Still to check
by hand on a machine without uv (rename `uv.exe` out of PATH, `UV_INSTALL_DIR` and
`%USERPROFILE%\.local\bin`): the tray shows the badge and the tooltip says "uv was not
found"; after installing uv and restarting VersionBar (the running app keeps the PATH it started
with; Retry alone only helps if uv is somewhere it already looks) the badge and plain tooltip
come back; the
"Open the uv install guide" button opens the browser (it uses `explorer.exe <url>`, which is
unverified in the running app); "Copy command" and "Copy error" put text on the clipboard
(the web clipboard API inside WebView2 is unverified in the running app). Ticket 31's manual QA
checklist should include these.

## Rust: what and why (ticket 22)

The popup can now tell the user what to do when there is nothing to show.

- **First run versus later runs.** Before starting uv, the shell checks whether the
  `core-env` folder exists in the app data folder. If not, this is the first run: uv has to
  create the environment and may download and install Python and packages, so it gets 180 seconds instead
  of 30, and the state says `setting_up` so the popup shows "One-time setup: preparing Python
  environment…" instead of a bare spinner. The check happens once, before the scan starts,
  so a folder that appears during the run does not shorten that run. The first-run rules
  then stay in force until one scan succeeds: if a first run times out after uv created the
  folder, Retry still gets 180 seconds and the setup screen, so uv can finish its download.
  The same applies if the folder was missing when the app started and the first scans failed
  for other reasons.
- **uv missing.** Unchanged logic (nothing is run, nothing is installed). The popup shows a
  copyable `winget install astral-sh.uv`, a button for the official install guide, and Retry
  (the existing `refresh`). Looking for uv now also happens before the "scanning" state is
  announced, so a missing uv goes straight to its screen without flashing the setup screen.
- **Failure.** The popup shows the shell's one-line message and the last 12 lines of uv's
  error output; Copy error copies the message and all of the error output. For timeouts and
  nonzero exits (and on the setup screen) it also says: "uv may download and install Python
  and packages for VersionBar's own environment. VersionBar never installs or changes your
  tools." Failures to start uv or unreadable output do not get that sentence, since downloads
  are not the likely cause.
- **Tray warning.** While the last scan found no uv, the tray icon gets a small warning dot
  and the tooltip says "uv was not found". The next scan that finds uv restores both, even if
  that scan then fails for another reason (the failure screen takes over the message). A
  refresh skipped because a scan is already running does not touch the tray. The dot is drawn
  from the normal icon at run time (`badge.rs`), so there is no second image to keep in step.
  The tray is updated from the scan thread after the scan ends, not from the state
  callback: that callback runs while the state is locked, a tray change waits for the main
  thread, and the main thread may be waiting for the same lock inside `get_state`.
- **Opening the install guide.** The popup cannot open links (no shell or opener plugin, on
  purpose). One new command, `open_uv_docs`, takes no arguments and opens one fixed address
  (`https://docs.astral.sh/uv/getting-started/installation/`) through Windows' own
  `explorer.exe`, found by full path in the Windows folder. The popup got one more permission
  for it (`allow-open-uv-docs`, listed in `tests/capabilities.rs`). It opens a web page and
  starts nothing else.
- **Copying.** Uses the browser clipboard API from the popup, so no clipboard plugin was
  added. If the webview refuses, the popup says so and the text stays on screen to select.

## Ticket 24 (2026-10-25)

Not run in the live tray. Still to check by hand (ticket 31's manual QA checklist should
include them):

- Right after launch, before ever opening the popup, choose Refresh in the tray menu: a scan
  runs (the saved file's `scanned_at` changes) and the popup, opened afterwards, shows it.
- Quit and relaunch: the popup opens on the saved results with their age ("Scanned 5 min
  ago") and "Scanning…" until the launch scan finishes.
- Leave the app running for over 30 minutes without touching it: `scan-state.json` is
  rewritten about every 30 minutes.
- Replace `scan-state.json` with garbage and relaunch: the app starts without results (the
  normal first-scan path) and does not crash; the next scan writes a good file.
- Ticket 12b-2: check that WebView2 delivers a DOM `focus` event on the shell's `set_focus`,
  so the search box refocuses each time the popup is reopened.

## Rust: what and why (ticket 24)

The shell now keeps its results across restarts and refreshes on its own. Details are in
`docs/app/state.md`.

- **Saving.** After every successful scan the shell writes the newest and the previous result
  to `scan-state.json` in the app data folder. It writes a temporary file first and then
  swaps it in, so a crash mid-write never leaves half a file. Failed scans do not touch the
  file. If the disk cannot be written the fresh results still show; only the saving is
  skipped.
- **Loading.** At launch it reads that file back, before the first scan. Like a live scan it
  checks only that each result is a JSON object with `schema_version` 1 and reads nothing
  else. A damaged file, a file from a different layout or a result from a newer version is
  ignored as a whole: the app starts empty, exactly as before this ticket, and the next scan
  overwrites the file. The popup therefore has data immediately after login.
- **Refreshing on its own.** A background timer scans at launch and then every 30 minutes.
  The timer runs in Rust, so it works whether or not the popup is open.
- **Refresh in the tray menu.** A new "Refresh" menu item (first in the menu) asks the
  scanner directly, not the popup, so it works before the popup has ever been opened and if
  its page is broken.
- **Requests that overlap.** Still never two scans at once. What changed: a refresh asked for
  while a scan runs used to be dropped; now the running scan is followed by exactly one more
  scan. Why: the user may just have edited the config, and the running scan started before
  that edit. Several requests during one scan still lead to only one extra scan.
- **No new permissions.** The popup can call the same three commands as before; the menu
  item and the timer are inside Rust. `tests/capabilities.rs` is unchanged.

## Ticket 25 (2026-10-25)

Checked with a debug build (`tauri build --debug --no-bundle`, assets embedded) on the same
machine with the dark system theme: the popup was opened through a second launch, driven with
synthetic mouse clicks and screenshotted.

### Verified

| Behaviour | Observation |
| --- | --- |
| Sizing | The popup keeps ticket 20's size (396×549 physical including the invisible frame, so about 380×540) and placement. Search box, list and status line fit; once rows are expanded the list scrolls with its own scrollbar while the header and search stay put. |
| Dark theme | Text, borders, badge and scrollbar follow the dark system theme. |
| Backdrop | The page background is a translucent tint, yet nothing of the windows behind shows through it, so the window has a system backdrop (Mica) behind the page. |
| Expanding | Clicking Git expands it to both installs with version, "Active", "On PATH", path and the three action buttons. |
| Copy path | Copied `C:\Program Files\Git\cmd\git.exe` exactly (read back from the Windows clipboard) and "Path copied" appeared in the status line, so the web clipboard API works inside WebView2. |
| Open containing folder | Opened an Explorer window on `C:\Program Files\Git\cmd` (a path with a space). The popup then hid, since Explorer took focus. |
| Focus | The search box has focus when the popup opens. |

### Not yet checked

- Light theme (the system theme was not switched on this machine), and switching theme while
  the popup is open.
- Whether Explorer visibly selects the file: the window opened on the right folder, but the
  selection was not inspected.
- Mica against different wallpapers, and the popup on Windows 10, which has no Mica: the page
  background is translucent, so without a backdrop the window may show what is behind it.
  Windows 10 is not a v1 target.
- Keyboard-only use: Tab order through search, rows, the not-found toggle and the action
  buttons.

## Rust: what and why (ticket 25)

- **Open containing folder.** One new command, `open_containing_folder`, takes one path from
  the popup and opens Explorer on the folder holding it, with the file selected. It is a
  command because the popup cannot start programs on its own (no shell plugin, on purpose).
- **Checking the path.** The shell never reads the scan, so it cannot tell whether the path
  came from one. Instead it accepts only a plain drive-letter path (`C:\...`, backslashes,
  no quotes, wildcards, control characters or extra colons) to a file that exists now.
  Network paths (`\\server\...`) and device paths (`\\?\...`) are refused before anything
  touches the disk, because Explorer would contact another machine or device for them. The
  exact rule is in `docs/app/actions.md`.
- **What runs.** Only `explorer.exe` from the Windows folder, by full path, with the single
  argument `/select,"<path>"`. Explorer shows the file and never runs it. The argument is
  written out by hand because Explorer does not understand Rust's usual quoting of a whole
  argument; refusing quotes in the path is what makes that safe. The shell does not wait for
  Explorer, which hands the request to the running Explorer and exits by itself.
- **Errors.** A refused path, a missing file, an unset Windows folder setting or a failed start
  each come back to the popup as one sentence it shows.
- **Permission.** The popup gained exactly one permission, `allow-open-containing-folder`, added
  to the reviewed list in `tests/capabilities.rs`. `tests/reveal.rs` checks the exact Explorer
  command for a path with a space and every kind of refused path, without starting Explorer.
- **Mica.** `tauri.conf.json` asks Windows for the Mica backdrop on the popup and makes the
  window transparent so the backdrop shows through the page. Mica follows the system light or
  dark theme by itself. No Rust code changed for it.
- **Copying** stays in the popup's web clipboard, as before: no clipboard plugin or command.

## Ticket 30 (2026-10-29)

App updates ([updates.md](updates.md)). Covered by tests on the controlled seams: the Rust
updater with a fake update source (`tests/update.rs`), the version marker (`tests/scan.rs`),
the capability guard (`tests/capabilities.rs`) and the banner through the IPC mock
(`app/src/Update.test.tsx`).

### Not yet checked

- The real update (DEV-11): install a CI-built prerelease, update it through the banner to the
  next CI-built full release on `releases/latest`, and record the versions, that app and core
  report the new version after the restart, and that the first scan afterwards ran as a setup
  run and succeeded. Needs a full release and an anonymously downloadable feed
  ([install-proof.md](install-proof.md) steps 3 and 8).
- A real signature failure and an offline check against the shipped plugin.

## Rust: what and why (ticket 30)

- **New dependency.** `tauri-plugin-updater` (official Tauri plugin, MIT/Apache-2.0), pinned
  exactly at `=2.14.1` like autostart, because it downloads and starts installers. Its TLS
  stack brings three crates under the ISC licence (`ring`, `rustls-webpki`, `untrusted`); ISC
  is a short permissive licence equivalent to MIT, so it was added to the allowed list in
  `deny.toml`.
- **Who decides.** All update work happens in Rust. The popup gets two new commands, both
  without arguments: `get_update` (what is on offer) and `install_update` (the user clicked the
  banner). It holds no permission of the updater plugin itself, so a page cannot check,
  download or install on its own; `tests/capabilities.rs` fails if one is ever granted.
- **When it goes online.** Only while the config's `update_check` is on, as last reported by
  the core's preferences query. Before the first answer at launch it counts as off, so nothing
  is requested until the user's setting is known. It then checks at once and every 24 hours.
  It looks again after every preferences query, so a change in the config file applies on the
  next refresh, without restart. Off: no more requests, and an offer already shown is hidden.
  On again: an offer the app had already found shows again at once, with no new request; the
  next request still waits until 24 hours after the last check.
- **Time limits.** One feed request may take 30 seconds and the installer download 15 minutes.
  A stalled request therefore ends as a failure instead of hanging, and a slow check never
  holds up an install the user confirmed.
- **Failures.** A failed check (offline, the feed missing while a release is being built, a
  broken feed) shows nothing and waits for the next daily check. A failure after the user
  confirmed (download, signature, installer) is shown in the banner with Retry. The scan
  results are never touched.
- **Installing.** The plugin downloads the installer, checks its signature against the public
  key in `tauri.conf.json`, starts it and closes the app; the installer reopens the new
  version. On other systems the app restarts itself.
- **After an update.** The app now writes its version to `core-env-version.txt` (next to the
  core's environment) after each successful scan. When the version differs, the next scan gets
  the long first-run allowance (180 seconds, "setting up"), because uv may need to download
  the new version's dependencies.
