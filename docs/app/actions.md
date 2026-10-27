# Popup: tool rows and install actions

What the popup's list shows and what each per-install action does. Code: `app/src/ToolList.tsx`
(rows and actions), `app/src/tools.ts` (what is derived from a scan), `app/src/feedback.ts`
(clipboard and the status line) and `app/src-tauri/src/reveal.rs` (opening a folder).

## Rows

- Each row shows the tool's name, its active version (or its status: Not found, Error, Timed
  out, or an unknown status as-is) and a "+N installs" badge counting the installs other than
  the active one. The active install is the one equal to `active`, never assumed to be first:
  a tool without an active install may still list installs that providers hold.
- Clicking a row (or Enter/Space on it) expands it to the tool's `notes` and every install:
  version, "Active" on the active one, "On PATH" or "From <provider>", "via <manager>" for a
  shim, the full path, and the three actions below.
- Error and timeout rows stay in the main list, in the error colour. Missing tools sit greyed
  in a section at the bottom, collapsed behind "Show not found (N)".
- Search matches the tool name or id, ignoring case. It also searches missing tools, which are
  shown without opening their section. Escape clears it. The search box has focus when the
  popup opens.

## Actions

| Action | How | Feedback |
|---|---|---|
| Copy version | `navigator.clipboard.writeText(version)` in the webview | "Version copied", or "Could not copy. Select the text instead." |
| Copy path | `navigator.clipboard.writeText(path)` in the webview | "Path copied", or the same failure text |
| Open containing folder | Rust command `open_containing_folder` with `{ path }` | "Opened in Explorer", or the shell's reason |

Feedback appears in one status line at the bottom of the popup (announced to screen readers)
and clears after four seconds.

Copying stays in the webview: there is no clipboard plugin or command, so the webview gains no
new permission for it. Versions and paths are also selectable text.

### Open containing folder

The shell never reads scan JSON, so it cannot check the path against the scan. It checks the
path itself and accepts only:

- a drive-absolute path (`C:\...`) written with backslashes,
- with no control characters, none of `" * ? < > | /`, and no colon except the drive's,
- naming a file that exists now.

That shuts out relative paths, network and device paths (`\\server\...`, `\\?\...`, which
Explorer would open by contacting something), alternate data streams, and quotes that could
end the quoted path. The form is checked before the disk is touched. An accepted path is
passed as `%SystemRoot%\explorer.exe /select,"<path>"`: Explorer opens the folder and selects
the file. Nothing at the path is run, and the webview cannot pass any other argument.

Refusals the user can see: "This is not a drive-letter path.", "This install no longer
exists.", "Explorer could not be found." (`SystemRoot` unset) and "Explorer could not be
started."

## Tray menu: Open config file and About

Menu order: Refresh, Show versions, Open config file, About, Quit. Code:
`app/src-tauri/src/config_file.rs` and the menu in `app/src-tauri/src/lib.rs`.

- **About** is the native About dialog. Its name and version come from the app's metadata
  (`productName` in tauri.conf.json, the crate version), not from literals.
- **Open config file** opens the `config_path` from the latest preferences query (DEC-13,
  DEC-22) with `%SystemRoot%\explorer.exe "<path>"`. The path must be a drive-absolute `.toml`
  path in the same plain-local form as the folder action; anything else is refused, because
  Explorer runs what it is given.
- When the file does not exist, its folder is created if needed and the starter template is
  written first. The write is create-only: an existing file is never opened for writing, so it
  is never overwritten or truncated. The template is `core/src/versionbar/starter_config.toml`,
  embedded at build time; a test asserts the embedded text equals that file.
- Nothing is cached: edits apply on the next refresh, which rereads preferences.
- The menu has no place for messages, so a failure goes to stderr. If the path is not known yet
  (no query has answered), the click starts a refresh so the next click has one.
