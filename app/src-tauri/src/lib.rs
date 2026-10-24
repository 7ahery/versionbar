//! The tray app's Rust shell: app lifecycle (tray, popup window, single instance) plus the
//! scoped scan and state commands.
//!
//! Everything about tools and versions lives in the core and the React UI (ADR-0006/0007).
//! The tray is built here at launch and never depends on the webview (ADR-0009).

use std::{
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

use tauri::{
    AppHandle, Emitter, Manager, PhysicalPosition, Runtime, WebviewWindow, WindowEvent,
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
};
use tauri_plugin_positioner::{Position, WindowExt};

pub mod scan;

use scan::{SCAN_TIMEOUT, ScanConfig, Scanner, ShellState};

/// Sent to the popup with the full `ShellState` whenever it changes.
const SCAN_UPDATED: &str = "scan-updated";

/// Where the installer puts the core project, inside the app's resource folder. Must match
/// `bundle.resources` in tauri.conf.json.
const BUNDLED_CORE: &str = "core";

/// The core's Python environment, inside the per-machine app data folder.
const CORE_ENVIRONMENT: &str = "core-env";

/// Window label of the popup, as declared in tauri.conf.json and the capabilities file.
const POPUP: &str = "popup";
const MENU_SHOW: &str = "show-versions";
const MENU_QUIT: &str = "quit";

/// Gap between the popup and the taskbar, like Windows 11's own flyouts (logical pixels).
const TASKBAR_GAP: f64 = 12.0;

/// Clicking the tray icon while the popup is open first takes focus away from the popup,
/// which hides it, and only then delivers the click. Without this grace period that click
/// would immediately reopen the popup, so the icon could never close it.
const REOPEN_GRACE: Duration = Duration::from_millis(300);

/// When the popup last hid itself because it lost focus.
#[derive(Default)]
struct LastBlurHide(Mutex<Option<Instant>>);

impl LastBlurHide {
    fn record_now(&self) {
        *self.0.lock().unwrap() = Some(Instant::now());
    }

    fn hid_recently(&self) -> bool {
        self.0
            .lock()
            .unwrap()
            .is_some_and(|at| at.elapsed() < REOPEN_GRACE)
    }
}

// Window calls below use `let _ =` deliberately: showing, hiding and moving the popup are
// best-effort. If one fails (for example while the window is being torn down at exit) there
// is nothing useful to do, and the tray must keep working regardless (ADR-0009).

pub fn run() {
    tauri::Builder::default()
        // Must be the first plugin: a second launch exits before anything else starts and
        // asks the running instance to show its popup instead of adding a second tray icon.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_popup(app);
        }))
        .plugin(tauri_plugin_positioner::init())
        .manage(LastBlurHide::default())
        .invoke_handler(tauri::generate_handler![get_state, refresh])
        .setup(|app| {
            create_tray(app.handle())?;
            let scanner = Arc::new(Scanner::new(
                scan_config(app.handle())?,
                announce(app.handle()),
            ));
            app.manage(scanner.clone());
            // Scan at launch so the popup has data by the time it is first opened.
            start_refresh(scanner);
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() != POPUP {
                return;
            }
            match event {
                WindowEvent::Focused(false) => {
                    if window.is_visible().unwrap_or(false) {
                        window.state::<LastBlurHide>().record_now();
                        let _ = window.hide();
                    }
                }
                // Alt+F4 must not destroy the popup (and with it the app): only hide it.
                WindowEvent::CloseRequested { api, .. } => {
                    api.prevent_close();
                    let _ = window.hide();
                }
                _ => {}
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to start the tray app");
}

fn scan_config<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<ScanConfig> {
    let paths = app.path();
    Ok(ScanConfig {
        find_uv: Box::new(|| scan::find_uv(&|key| std::env::var_os(key))),
        project: paths.resource_dir()?.join(BUNDLED_CORE),
        // Local, not roaming: the environment is large and specific to this machine.
        environment: paths.app_local_data_dir()?.join(CORE_ENVIRONMENT),
        timeout: SCAN_TIMEOUT,
    })
}

fn announce<R: Runtime>(app: &AppHandle<R>) -> scan::Notify {
    let app = app.clone();
    Box::new(move |state: &ShellState| {
        // No popup listening yet is normal; it asks with `get_state` when it loads.
        let _ = app.emit(SCAN_UPDATED, state);
    })
}

/// Scans on a background thread so neither IPC nor the tray waits for the core.
fn start_refresh(scanner: Arc<Scanner>) {
    thread::spawn(move || {
        scanner.refresh();
    });
}

/// The popup's view of the scan state: current and previous results plus progress.
#[tauri::command]
fn get_state(scanner: tauri::State<'_, Arc<Scanner>>) -> ShellState {
    scanner.state()
}

/// Starts a scan and returns at once; the result arrives as a `scan-updated` event. Does
/// nothing while a scan is already running.
#[tauri::command]
fn refresh(scanner: tauri::State<'_, Arc<Scanner>>) {
    start_refresh(scanner.inner().clone());
}

fn create_tray<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    // Show versions is always in the menu: Linux trays do not report left-clicks (ADR-0009).
    let menu = Menu::with_items(
        app,
        &[
            &MenuItem::with_id(app, MENU_SHOW, "Show versions", true, None::<&str>)?,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(app, MENU_QUIT, "Quit", true, None::<&str>)?,
        ],
    )?;

    let mut tray = TrayIconBuilder::new()
        .tooltip(&app.package_info().name)
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            MENU_SHOW => show_popup(app),
            MENU_QUIT => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            // Lets the positioner anchor the popup to wherever the icon currently is.
            tauri_plugin_positioner::on_tray_event(tray.app_handle(), &event);
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                toggle_popup(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

fn popup<R: Runtime>(app: &AppHandle<R>) -> Option<WebviewWindow<R>> {
    app.get_webview_window(POPUP)
}

fn toggle_popup<R: Runtime>(app: &AppHandle<R>) {
    let Some(window) = popup(app) else { return };
    if window.is_visible().unwrap_or(false) {
        let _ = window.hide();
        return;
    }
    if !app.state::<LastBlurHide>().hid_recently() {
        show_popup(app);
    }
}

fn show_popup<R: Runtime>(app: &AppHandle<R>) {
    let Some(window) = popup(app) else { return };
    place_near_tray(&window);
    let _ = window.unminimize();
    let _ = window.show();
    let _ = window.set_focus();
}

/// Anchors the popup above the tray icon, inside the screen area the taskbar leaves free.
fn place_near_tray<R: Runtime>(window: &WebviewWindow<R>) {
    // The tray position is unknown until the icon has reported a mouse event (for example
    // when a second launch asks to show the popup), so fall back to the usual tray corner.
    if window
        .move_window_constrained(Position::TrayCenter)
        .is_err()
    {
        let _ = window.move_window(Position::BottomRight);
    }
    // Second pass: positioner 2.4.0 keeps the window on the monitor, not inside the work
    // area, and its BottomRight fallback ignores the taskbar, so either can overlap it.
    let (Ok(Some(monitor)), Ok(pos), Ok(size)) = (
        window.current_monitor(),
        window.outer_position(),
        window.outer_size(),
    ) else {
        return;
    };
    let area = monitor.work_area();
    let gap = (TASKBAR_GAP * monitor.scale_factor()).round() as i32;
    let (width, height) = (size.width as i32, size.height as i32);
    let (left, top) = (area.position.x, area.position.y);
    let right = left + area.size.width as i32;
    let bottom = top + area.size.height as i32;
    let x = pos
        .x
        .clamp(left + gap, (right - gap - width).max(left + gap));
    let y = pos
        .y
        .clamp(top + gap, (bottom - gap - height).max(top + gap));
    let _ = window.set_position(PhysicalPosition::new(x, y));
}
