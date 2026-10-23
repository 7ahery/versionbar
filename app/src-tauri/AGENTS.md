# Rust shell agent guide

Applies to everything under `app/src-tauri/`. Root rules in `../../AGENTS.md` also apply. The maintainer does not know Rust: keep the surface small and stable, and explain every change in plain English in the PR.

- **Scope:** app lifecycle and narrowly scoped commands only. No business logic about tools or versions.
- **No shell plugin.** Never give the webview a way to spawn arbitrary processes. Add one scoped command per feature (scan, get state, refresh, copy, open containing folder, open config file).
- **Opaque JSON.** Hold the current and previous scan results as raw JSON, check only `schema_version`, never deserialize deeper. Diffing and sorting belong to the UI.
- **Tray and menu** are created at launch and must survive webview reloads and crashes. Left-click toggles the popup; the full menu offers Refresh, Show versions, Open config file, Start with Windows (off by default), About, Quit. It is built incrementally: Show versions and Quit first (ticket 20), the full menu by ticket 27. Refresh must work without the webview.
- **Popup:** frameless, about 380x540, anchored above the tray, hides on focus loss, recreated if the webview dies.
- **Plugins:** autostart, single-instance, positioner and updater only.
- **Scan command:** locate uv (PATH, then `UV_INSTALL_DIR`, then default user-local bin); run the bundled core with frozen dependencies, a uv-managed Python only, and the project environment in the app data folder; fixed arguments `list --json`; 30 s timeout, 180 s on first run; capture stderr; report one of uv missing, setting up, failed (with stderr), ok. The uv path must be injectable for tests.
- **Two fixed core invocations only:** the scan above and the preferences query (added by ticket 12a). Rust never parses TOML and never accepts arbitrary arguments. The update-check flag and the config file path come from the preferences query, not from Rust reading config.
- **Never install anything** (including uv) on the user's behalf.
- **Updater:** check at startup and every 24 h unless disabled (the flag comes from the preferences query); install only after the user confirms. Update metadata is signed with the Tauri updater key; the installer itself is unsigned in v1.
- **Checks:** rustfmt, `clippy -D warnings`, cargo-deny, tests. Test scan and state commands with a fake `uv`; do not unit test tray or window behaviour.
