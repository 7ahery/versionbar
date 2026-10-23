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
