fn main() {
    // Declaring the app's own commands makes Tauri generate one permission per command
    // (`allow-get-state`, `allow-get-preferences`, `allow-refresh`, `allow-open-uv-docs`,
    // `allow-open-containing-folder`, `allow-get-update`, `allow-install-update`),
    // so the popup can call only what capabilities/default.json grants it
    // (tests/capabilities.rs).
    let commands = tauri_build::AppManifest::new().commands(&[
        "get_state",
        "get_preferences",
        "refresh",
        "open_uv_docs",
        "open_containing_folder",
        "get_update",
        "install_update",
    ]);
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(commands))
        .expect("failed to run the Tauri build script");
    embed_manifest_in_tests();
}

/// Tauri embeds its Windows manifest (Common Controls 6) in the app executable only. Test
/// binaries that start the mock runtime (tests/popup.rs) load the same Windows UI code and
/// exit with STATUS_ENTRYPOINT_NOT_FOUND without it, so the linker embeds a copy of Tauri's
/// default manifest into test binaries; the app executable is left as Tauri builds it.
fn embed_manifest_in_tests() {
    let target_os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    let target_env = std::env::var("CARGO_CFG_TARGET_ENV").unwrap_or_default();
    if target_os != "windows" || target_env != "msvc" {
        return;
    }
    let manifest = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("windows-app-manifest.xml");
    println!("cargo:rerun-if-changed={}", manifest.display());
    println!("cargo:rustc-link-arg-tests=/MANIFEST:EMBED");
    println!(
        "cargo:rustc-link-arg-tests=/MANIFESTINPUT:{}",
        manifest.display()
    );
}
