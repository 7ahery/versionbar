# VersionBar agent guide

VersionBar inventories the dev tools on a machine. The `versionbar` CLI (Python core) is the product; the Windows tray app (Tauri) is one consumer of it. Read `GLOSSARY.md` for vocabulary and `docs/adr/` for settled decisions before changing architecture. If your change contradicts an ADR, surface that explicitly rather than overriding it silently.

Scoped guides add rules for their directory: `core/AGENTS.md` (Python core) and `app/src-tauri/AGENTS.md` (Rust shell).

## Repository identity

- The GitHub repository is `7ahery/versionbar`. The spec (#1) and some older notes say `7ahery/version-bar`; that was the provisional name, and the local checkout folder is still `version-bar`. Use `7ahery/versionbar` for URLs, release config and badges.
- Names are provisional and defined in few places (core package metadata, Tauri config, one TS constant). Derive everything else from them; never hard-code the name elsewhere.
- Display name VersionBar, PyPI package and command `versionbar`, bundle id `io.github.7ahery.versionbar`. Licence MIT.

## Layout

Three-part monorepo with one shared version number (the core's package metadata is the source of truth):

- `core/`: Python package (3.14+, uv only), CLI, tool definitions, providers.
- `app/`: Tauri app. `app/src-tauri/` is the Rust shell; the React/TS UI sits beside it.
- `schema/`: generated JSON Schema and TS types, committed.

## Hard rules

1. **Rust does lifecycle and narrowly scoped commands only.** Each new capability gets its own scoped command.
2. **Rust treats scan JSON as opaque.** It checks `schema_version` only and never reads deeper. All meaning (parsing, diffing, sorting, search) lives in the React UI.
3. **No shell plugin.** The webview must not be able to spawn arbitrary processes.
4. **Every tool and provider needs a captured-output fixture** recorded with `versionbar debug capture`. Until that command exists (ticket 05), a real capture seeded by hand is acceptable if it is attributable (which machine and command produced it, recorded next to the fixture). Do not invent output strings. Nothing ships without real captured output.
5. **Never install anything for the user.** VersionBar reports; it does not install, upgrade or switch tools, including uv. The app shows a copyable command instead.
6. **The core never caches.** Every CLI invocation scans live. Only the Rust shell stores scan results.
7. **uv is a hard prerequisite.** The core runs on a uv-managed Python, never the system Python it reports on.
8. **Pydantic models are the single source of truth for the JSON contract.** Change the models, then run `npm run gen`; CI fails on stale schema or TS types. `schema_version` is bumped only for breaking changes.
9. **All machine access goes through the injectable system interface** in the core. No direct process, environment or filesystem calls elsewhere.
10. **No telemetry.** The app goes online only for update checks (disableable in config; the flag reaches Rust through the core's preferences query) and uv's own downloads. Do not add any other network access anywhere.

## Testing

- Test behaviour through the public seam only, checking observable output, never internals.
- Three seams: core CLI over a fake system built from fixtures; Rust scan/state commands with an injected fake `uv`; UI through Tauri's IPC mock. Tray and window behaviour is not unit tested.
- Fixtures are real captured output, stored per tool and per provider.
- Core tests also run on Ubuntu. A Windows CI smoke test runs `versionbar list --json` against the real machine.
- No automated end-to-end tests of the running app; a manual QA checklist covers each release.

## Install and scan rules

- The scan command finds uv on PATH, then `UV_INSTALL_DIR`, then the default user-local bin, and keeps the Python environment in the app data folder (not the install folder).
- The app may run exactly two fixed core invocations: the scan (`list --json`) and the preferences query (added by ticket 12a). Rust never parses TOML and never accepts arbitrary arguments; config values it needs (update-check flag, config file path) come from the preferences query.
- VersionBar never installs uv or anything else on its own.

## Distribution and signing

Keep two things apart:

- The NSIS installer and Windows executables are **unsigned** in v1. Users verify them with published SHA-256 checksums and the README explains the SmartScreen warning. SignPath comes later.
- Updater metadata and artifacts **are cryptographically signed** with Tauri's updater key, held as a CI secret. Do not describe the updater as unsigned or the installer as signed.

Releases come from CI only (release-please, Conventional Commit PR titles, tag-triggered build, PyPI Trusted Publishing). Never build a release locally.

## Workflow

- PR titles must follow Conventional Commits (CI-enforced); commit messages should too.
- Root npm scripts are the one interface: `dev`, `cli`, `test`, `lint`, `gen`, `doctor`, `build`. Run `lint` and `test` before finishing.
- Windows setup: see `docs/setup/windows.md`.
- Every PR touching Rust must include a plain-English "what and why" section (see `.github/pull_request_template.md`). The maintainer does not know Rust and reviews behaviour from that explanation.
- Comments explain why, not what.
