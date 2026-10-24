fn main() {
    // Declaring the app's own commands makes Tauri generate one permission per command
    // (`allow-get-state`, `allow-refresh`), so the popup can call only what
    // capabilities/default.json grants it (tests/capabilities.rs).
    let commands = tauri_build::AppManifest::new().commands(&["get_state", "refresh"]);
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(commands))
        .expect("failed to run the Tauri build script");
}
