# Installer: CI build and install proof

The `Installer` workflow (`.github/workflows/installer.yml`) builds the per-user NSIS installer on a clean `windows-latest` runner with `npm run build`, and uploads it with `SHA256SUMS.txt` as the artifact `installer-<commit sha>`. It runs on every push to a `ticket/**` or `integration/**` branch, on manual dispatch, and can be called by the release workflow later. It does not sign anything: the installer is unsigned in v1.

## Verify a download

1. Download the artifact in a browser and unzip it with Explorer (or, for a release, download the installer and `SHA256SUMS.txt`). Chrome blocks the unsigned installer as dangerous: open `chrome://downloads` and choose **Keep** (in some versions under the entry's menu). Downloading another way (`gh run download`, some archivers) drops the Mark-of-the-Web, and SmartScreen then shows no warning.
2. In PowerShell, in the folder that holds both files:

   ```powershell
   (Get-FileHash -Algorithm SHA256 .\VersionBar_<version>_x64-setup.exe).Hash.ToLower()
   Get-Content .\SHA256SUMS.txt
   ```

   The two hashes must be identical. Do not run the installer if they differ.

## SmartScreen

Windows SmartScreen shows "Windows protected your PC" for unsigned installers, because no certificate vouches for the publisher. After verifying the checksum, choose "More info", then "Run anyway". The installer needs no administrator rights: it installs for the current user only.

## What the installer contains

`npm run build` runs `tauri build`. `bundle.targets` (`nsis`), `bundle.windows.nsis.installMode` (`currentUser`, so no administrator rights) and `bundle.resources` live in `app/src-tauri/tauri.conf.json`. The resources copy `core/pyproject.toml`, `uv.lock`, `.python-version`, `README.md` and `src/` from the same checkout into the installed `core/` folder, so the bundled core always matches the app commit. The layout and the app-data environment are described in [bundled-core.md](bundled-core.md).

## Human install proof (checklist for the maintainer)

Done by a person on a real Windows machine that has uv. CI cannot do it, and no evidence is recorded until someone has. Leave the ticket open for any failed check. Never substitute a locally built installer.

Setup: take the installer from a green `Installer` run and verify its SHA-256 as above. For the system-Python proof, note whether a system Python is on PATH.

Install and first run

1. Run the installer. Confirm the SmartScreen warning appears and "Run anyway" works, and that there is no UAC prompt. Confirm it installed under `%LOCALAPPDATA%\Programs`, not Program Files.
2. Launch the app. Confirm the tray icon appears and the popup opens from it.
3. First run: note how long the first preparation takes (uv downloads Python and packages) and what the popup shows meanwhile. Confirm it ends with a live scan of the tools.
4. Confirm `%LOCALAPPDATA%\io.github.7ahery.versionbar\core-env` was created by the app at runtime, and that nothing was written into the install folder.
5. Use Refresh and confirm a new scan appears.

uv discovery

6. Missing uv: hide uv (rename it, and remove it from PATH, `UV_INSTALL_DIR` and the default user-local bin), launch, and confirm the popup shows the uv-missing state with a copyable install command. The app must not install anything. Restore uv, use Refresh, and confirm it recovers without a restart.
7. Fallback without an interactive shell PATH: start the app from the Start menu or at login, with a PATH that lacks uv and uv only in `UV_INSTALL_DIR` or the default user-local bin (`%USERPROFILE%\.local\bin`). Confirm the scan works.

Independence

8. Confirm the installed app uses neither the checkout nor the system Python: move or rename any repo checkout and, if possible, remove the system Python from PATH; scans must still work. In Process Explorer or Task Manager, check that the running `python.exe` lives under uv's managed Python folder and `core-env`, and that the `versionbar` code is loaded from the install folder's `core`.

Uninstall and upgrade

9. Uninstall from Settings, Apps with no UAC prompt. Confirm the tray icon is gone and the install folder is removed. Record what happens to `core-env` in app data.
10. Reinstall, and also install a newer CI installer over an older one (different commits, ideally with a changed `uv.lock`). Confirm `core-env` is kept, the next scan re-syncs it to the new bundled version and dependencies, and the scan still works.

Record the date, Windows version, commit, and the result and timing of each step in [native-observations.md](native-observations.md).
