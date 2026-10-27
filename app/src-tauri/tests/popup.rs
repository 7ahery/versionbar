//! Showing the popup from the tray menu and from a second launch, on Tauri's mock runtime.
//!
//! The mock runtime reports every window as visible and has no real tray, so these tests check
//! which windows exist, not what is on screen; position and focus are covered by manual QA.
//! Its event loop never runs here, so a destroyed window would never leave the app's window
//! list: a popup whose window is gone is modelled by an app that has no popup window.

use tauri::{
    App, Config, Manager, WebviewWindowBuilder,
    test::{MockRuntime, mock_builder, mock_context, noop_assets},
};

/// The popup label from tauri.conf.json and the capabilities file.
const POPUP: &str = "popup";

/// An app with the real window config from tauri.conf.json but no popup window, as after the
/// popup's window died.
fn app_without_popup() -> App<MockRuntime> {
    let mut context = mock_context(noop_assets());
    context.config_mut().app.windows = real_config().app.windows;
    mock_builder()
        .plugin(tauri_plugin_positioner::init())
        .build(context)
        .expect("mock app builds")
}

/// The same app with the popup created from its config, as Tauri does when the shipped app
/// starts (the mock app is never run, so Tauri does not do it here).
fn app_with_popup() -> App<MockRuntime> {
    let app = app_without_popup();
    let config = real_config();
    let popup = config
        .app
        .windows
        .iter()
        .find(|window| window.label == POPUP)
        .expect("tauri.conf.json declares the popup");
    WebviewWindowBuilder::from_config(&app, popup)
        .and_then(|builder| builder.build())
        .expect("popup created");
    app
}

fn real_config() -> Config {
    serde_json::from_str(include_str!("../tauri.conf.json")).expect("tauri.conf.json parses")
}

#[test]
fn show_versions_recreates_the_popup_when_its_window_is_gone() {
    let app = app_without_popup();

    tray_shell::show_popup(app.handle());

    assert_eq!(app.webview_windows().keys().collect::<Vec<_>>(), [POPUP]);
}

#[test]
fn show_versions_reuses_a_popup_that_exists() {
    let app = app_with_popup();

    tray_shell::show_popup(app.handle());

    assert_eq!(app.webview_windows().keys().collect::<Vec<_>>(), [POPUP]);
}

#[test]
fn a_second_launch_shows_the_existing_popup_and_adds_no_tray() {
    let app = app_with_popup();

    tray_shell::on_second_launch(app.handle());

    assert_eq!(
        app.webview_windows().keys().collect::<Vec<_>>(),
        [POPUP],
        "a second launch must not open another window"
    );
    assert!(
        app.tray_by_id("main").is_none(),
        "a second launch must not build a tray"
    );
}

#[test]
fn a_second_launch_recreates_the_popup_when_its_window_is_gone() {
    let app = app_without_popup();

    tray_shell::on_second_launch(app.handle());

    assert_eq!(app.webview_windows().keys().collect::<Vec<_>>(), [POPUP]);
}
