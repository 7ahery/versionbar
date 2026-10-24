# Troubleshooting the tray app

The VersionBar tray app runs its scanner with [uv](https://docs.astral.sh/uv/). VersionBar
never installs uv or any other tool for you. When something goes wrong the popup shows what
happened and what to do. Every screen has a **Retry** button, which scans again.

## "uv was not found"

The app looks for uv on your PATH, then in the folder named by `UV_INSTALL_DIR`, then in
`%USERPROFILE%\.local\bin`. If it is in none of them, the tray icon also shows a warning dot.

1. Install uv yourself. In a terminal run:

   ```
   winget install astral-sh.uv
   ```

   The popup has a **Copy command** button for this, and an **Open the uv install guide**
   button for the other ways to install it
   (<https://docs.astral.sh/uv/getting-started/installation/>).
2. Press **Retry**. A new terminal is not needed, but if uv still is not found, restart
   VersionBar so it sees your updated PATH.

## "One-time setup: preparing Python environment…" is slow, or then fails

The first scan creates VersionBar's own Python environment in
`%LOCALAPPDATA%\io.github.7ahery.versionbar\core-env`. uv may download and install a Python
and packages for it, so this can take a few minutes; the app allows 180 seconds for it. It
happens once. VersionBar never installs or changes your tools.

If the setup times out or fails with a download error:

- Check your network connection, proxy or mirror settings (uv honours its usual `UV_...`
  network settings and the proxy environment variables).
- Press **Retry**. uv continues from what it already downloaded, and the retry also gets the
  180-second allowance.
- If it keeps failing, use **Copy error** and include the text in a bug report.

## "The scan failed"

The popup shows a one-line reason and the last lines of the error output.

- **Timed out or exited with an error:** press **Retry**. If it repeats, press **Copy error**
  and report it.
- **Unreadable output or an unsupported result version:** the installed app and its bundled
  scanner do not agree (a damaged or mixed install). Reinstall the same VersionBar release.
  If that does not help, **Copy error** and report it.
- **Could not start uv:** uv was found but could not be run (for example, a broken
  installation). Reinstall uv, then **Retry**.

When you report a problem, paste the copied text and your VersionBar version (shown in the
popup header) at <https://github.com/7ahery/versionbar/issues>.
