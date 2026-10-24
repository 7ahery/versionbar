fn main() {
    // Declaring the app's own commands makes Tauri generate one permission per command
    // (`allow-get-state`, `allow-refresh`, `allow-open-uv-docs`), so the popup can call only what
    // capabilities/default.json grants it (tests/capabilities.rs).
    let commands =
        tauri_build::AppManifest::new().commands(&["get_state", "refresh", "open_uv_docs"]);
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(commands))
        .expect("failed to run the Tauri build script");
}
