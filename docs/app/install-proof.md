# Installer: CI build and install proof

The `Installer` workflow (`.github/workflows/installer.yml`) builds the per-user NSIS installer on a clean `windows-latest` runner with `npm run build`, and uploads it with `SHA256SUMS.txt` as the artifact `installer-<commit sha>`. It runs on every push to a `ticket/**` or `integration/**` branch, on manual dispatch, and can be called by the release workflow later. It does not sign anything: the installer is unsigned in v1.

## Verify a download

1. Download and unzip the artifact (or, for a release, download the installer and `SHA256SUMS.txt`).
2. In PowerShell, in the folder that holds both files:

   ```powershell
   (Get-FileHash -Algorithm SHA256 .\VersionBar_<version>_x64-setup.exe).Hash.ToLower()
   Get-Content .\SHA256SUMS.txt
   ```

   The two hashes must be identical. Do not run the installer if they differ.

## SmartScreen

Windows SmartScreen shows "Windows protected your PC" for unsigned installers, because no certificate vouches for the publisher. After verifying the checksum, choose "More info", then "Run anyway". The installer needs no administrator rights: it installs for the current user only.

## Human install proof (checklist for the maintainer)

Done by a person on a Windows machine that has uv but not this repo. CI cannot do it, and no evidence is recorded until someone has.

1. Take the installer artifact from a green `Installer` run and verify its SHA-256 as above.
2. Run the installer. Confirm the SmartScreen warning appears and "Run anyway" works. Confirm there is no UAC prompt.
3. Confirm the tray icon appears and the popup opens from it.
4. Confirm the popup lists the tools (uv must be on PATH, in `UV_INSTALL_DIR` or in the default user-local bin).
5. Uninstall from Settings, Apps. Confirm the tray icon is gone and `%LOCALAPPDATA%\Programs\VersionBar` is removed.
6. Record the date, Windows version, commit and the result of each step in [native-observations.md](native-observations.md).
