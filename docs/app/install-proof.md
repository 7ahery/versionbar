# Installer: CI build and install proof

The `Installer` workflow (`.github/workflows/installer.yml`) builds the per-user NSIS installer on a clean `windows-latest` runner with `npm run build`, and uploads it with `SHA256SUMS.txt` as the artifact `installer-<commit sha>`. It runs on every push to a `ticket/**` or `integration/**` branch and on manual dispatch; those builds sign nothing. The release workflow calls it with `sign-updater: true`, which adds the signed updater signature (`<installer>.sig`) to the artifact; see the README's Releases section. The installer itself is unsigned in v1 either way.

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

## Release gate (checklist for the maintainer)

Done by a person before the first production release. No evidence is recorded until someone has. Authenticode signing is out of scope (ADR 0010).

Updater key and secrets

1. Keep the updater private key and its password outside the repository (a password manager). The public key is already in `plugins.updater.pubkey` in `app/src-tauri/tauri.conf.json`; if the key pair is ever replaced, update it there in the same change.
2. Create the environment `release` (Settings, Environments). Under Deployment branches and tags choose Selected branches and tags and add `main` only. Add the environment secrets `TAURI_SIGNING_PRIVATE_KEY` (the key file's content) and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`. Do not also add them as repository secrets: those would be readable from any branch.
3. Before relying on the updater, confirm from a signed-out browser or `curl` without credentials that a release's assets and `https://github.com/7ahery/versionbar/releases/latest/download/latest.json` download anonymously. While the repository is private they will not, and installed apps cannot update.

Prerelease rehearsal

4. Trigger a prerelease from CI, never from a local build: land a commit on `main` whose message ends with the footer `Release-As: 0.1.0-rc.1`, for example a PR containing `git commit --allow-empty -m "chore: release 0.1.0-rc.1" -m "Release-As: 0.1.0-rc.1"`. With a squash merge, check that the footer is still in the squashed commit's description. release-please then opens a release PR for `0.1.0-rc.1`; merge it. For the next full release, use a `Release-As: 0.1.0` footer the same way so the version is not guessed from the prerelease.
5. Confirm the release page shows the release as **Pre-release** and that `releases/latest` still points at the previous full release (or 404s if there is none) before going on. If it shows as a normal release, stop: installed apps would be offered it.
6. Record the published version and tag, the release's assets (installer, `.sig`, `SHA256SUMS.txt`, `latest.json`), and the installer's SHA-256 checked against `SHA256SUMS.txt` as in [Verify a download](#verify-a-download).
7. Check the prerelease's own feed, `https://github.com/7ahery/versionbar/releases/download/v0.1.0-rc.1/latest.json`, not `releases/latest` (which never serves a prerelease): it downloads anonymously, `version` matches the tag, `platforms.windows-x86_64.url` downloads that release's installer, and `signature` is the `.sig` file's content. While the repository is private, use a controlled reachable test feed instead and record which one was used.
8. Verify the signature against the public key. The `.sig` file and `plugins.updater.pubkey` are both base64-encoded minisign files: decode each to a file and run `minisign -V -p <decoded pubkey> -m <installer> -x <decoded sig>` (the Tauri CLI has no verify command). The shipped feed only serves full releases, so the in-app update is proved from an installed prerelease (for example `0.1.0-rc.1`) to the next CI-built full release on `releases/latest`, once the feed downloads anonymously (step 3; DEV-11): wait for the banner `Update to v<version> → Install & restart` (update checks on), confirm it, and after the restart record that the app and the core report the new version and the next scan succeeds ([updates.md](updates.md)).

If a release run fails after release-please has published the release, the release has no assets and `releases/latest/download/latest.json` returns 404 (for a full release) until the failed jobs are re-run with Re-run failed jobs on that workflow run (re-run first; a real defect ships in the next patch release, as below). The same 404 is normal while a full release is still building. While it lasts, installed apps' update checks fail with an error (the Tauri updater counts only 204 as "no update"); the app shows nothing for a failed check, keeps any earlier offer and tries again at its next daily check ([updates.md](updates.md#failures)).

Record the date, versions, checksums and results in [native-observations.md](native-observations.md).

## PyPI publication and retry (#33)

The release run also builds the wheel and sdist once (`build-dist`), installs those exact files into throwaway uv tool folders on Windows and Ubuntu (`verify-dist`), and only then uploads them (`publish-pypi`, PyPI Trusted Publishing: no token, environment `pypi`). The published version is the release tag as PEP 440 (`v0.1.0-rc.1` becomes `0.1.0rc1`); the run stops before building if the version files disagree with the tag.

Retrying a failed PyPI side. Use **Re-run failed jobs** on the same release-please run first; a re-run never needs a new version or tag.
- The PyPI jobs and the installer jobs are independent, so one side can fail and be re-run while the other stays green. Each failure shows in the run.
- A re-run of `publish-pypi` uploads the identical files built by the first attempt, and `skip-existing` makes it finish a partial upload instead of failing on files PyPI already has. PyPI never accepts a different file under a version number it has seen, so do not bump the version to "fix" a half-published release; fix the cause and re-run.
- If `build-dist`, `verify-dist` or `publish-pypi` failed, first use **Re-run failed jobs** on the same run. `verify-dist` resolves dependencies from PyPI on two runners, so a transient failure is likely, and nothing was published by a failed `build-dist` or `verify-dist`.
- Only if the failure is a real defect that re-running cannot fix: fix it on `main` and let the next patch release ship the app and the PyPI package together. Then add a note to the broken version's GitHub release that it has no PyPI package (`gh release edit <tag> --notes-file`, keeping the existing notes), so nobody waits for it.
- If PyPI rejected the upload with an identity error, the Trusted Publisher does not match: it must be owner `7ahery`, repository `versionbar`, workflow `release-please.yml`, environment `pypi`. Fix it on pypi.org and re-run.

One-time setup by the maintainer (before the first release)

1. Check that the name `versionbar` is free on PyPI. If someone else holds it, stop and decide the new name explicitly (names are defined in few places, see AGENTS.md).
2. On pypi.org, Your account, Publishing, add a pending publisher: project `versionbar`, owner `7ahery`, repository `versionbar`, workflow `release-please.yml`, environment `pypi`. A pending publisher does not reserve the name until the first publish.
3. Create the environment `pypi` (Settings, Environments), limited to the `main` branch. It needs no secrets.
4. After two published prereleases, record the isolated-environment proof in [pypi-evidence.md](../pypi-evidence.md). The upgrade sequence is: `uv tool install "versionbar>=<rc1>" --prerelease allow` while `<rc1>` is the newest version, `uvx --from "versionbar==<rc1>" versionbar --version`, then `uv tool upgrade versionbar --prerelease allow` once `<rc2>` is published. Do not install with `==`: uv keeps the exact pin and the upgrade does nothing. Checked with uv 0.12.23 on real PyPI prereleases (details in pypi-evidence.md).

Prerelease marking. The `mark-prerelease` job flags a `-rc` release as a GitHub prerelease before anything is built (`verify-release` needs it). If it fails, the release exists and may be shown as the latest release for a moment: use **Re-run failed jobs** on the same run, which re-runs only that job with the original outputs and then the jobs that wait for it. If re-running cannot work, mark it by hand (`gh release edit <tag> --prerelease --latest=false`) and re-run the failed jobs anyway; do not start a new release.
