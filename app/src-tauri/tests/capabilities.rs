//! Guardrail: what the popup webview is allowed to call.
//!
//! Capabilities are the webview's whole attack surface, so widening them must be a
//! deliberate, reviewed change: add the new permission to `REVIEWED` in the same PR
//! that adds the scoped command, and explain it in the PR's Rust section.

use std::{fs, path::Path};

use serde_json::Value;

/// Every permission the webview may hold. One entry per scoped command; never shell or
/// process access (AGENTS.md hard rule 3).
const REVIEWED: &[&str] = &[
    // Popup header shows the app version.
    "core:app:allow-version",
    // The scan state (current and previous results, progress, last outcome); read only.
    "allow-get-state",
    // The preferences answer (config path, problems, pinned/order, update flag) and how the
    // latest query went; read only, takes no arguments.
    "allow-get-preferences",
    // Starts a scan job: the fixed `config --json` then `list --json` invocations; takes no
    // arguments.
    "allow-refresh",
    // Opens one fixed page, the official uv installation guide, in the default browser; takes
    // no arguments, so the webview cannot make the shell open anything else.
    "allow-open-uv-docs",
    // Shows one install in Explorer with the file selected. Takes a path, accepted only as an
    // existing file at a drive-letter path in plain form (src/reveal.rs); Explorer selects it and
    // never runs it.
    "allow-open-containing-folder",
    // Subscribe to and drop the `scan-updated` and `preferences-updated` events. Listening
    // only: the webview cannot emit events.
    "core:event:allow-listen",
    "core:event:allow-unlisten",
];

fn capabilities() -> Vec<(String, Value)> {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("capabilities");
    let mut found: Vec<(String, Value)> = fs::read_dir(&dir)
        .expect("capabilities directory exists")
        .map(|entry| entry.expect("readable directory entry").path())
        .filter(|path| path.extension().is_some_and(|ext| ext == "json"))
        .map(|path| {
            let text = fs::read_to_string(&path).expect("readable capability file");
            let json = serde_json::from_str(&text).expect("capability file is valid JSON");
            (path.display().to_string(), json)
        })
        .collect();
    found.sort_by(|a, b| a.0.cmp(&b.0));
    assert!(
        !found.is_empty(),
        "no capability files in {}",
        dir.display()
    );
    found
}

#[test]
fn webview_holds_only_reviewed_permissions() {
    for (file, capability) in capabilities() {
        let permissions = capability["permissions"]
            .as_array()
            .unwrap_or_else(|| panic!("{file}: `permissions` must be a list"));
        for permission in permissions {
            // Object entries carry scopes; the identifier is what grants access.
            let id = permission
                .as_str()
                .or_else(|| permission["identifier"].as_str())
                .unwrap_or_else(|| panic!("{file}: permission without identifier"));
            assert!(
                REVIEWED.contains(&id),
                "{file}: permission `{id}` is not in the reviewed list"
            );
        }
    }
}

#[test]
fn capabilities_apply_only_to_the_bundled_popup() {
    for (file, capability) in capabilities() {
        assert!(
            capability.get("remote").is_none(),
            "{file}: remote URLs must never get IPC access"
        );
        assert_eq!(
            capability["windows"],
            serde_json::json!(["popup"]),
            "{file}: capabilities target the popup window only"
        );
    }
}
