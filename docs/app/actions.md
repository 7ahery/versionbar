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

Refusals the user can see: "This is not a path on a local drive.", "This install no longer
exists.", "Explorer could not be found." (`SystemRoot` unset) and "Explorer could not be
started."
