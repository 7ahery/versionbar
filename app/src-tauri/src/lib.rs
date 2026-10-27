//! The tray app's Rust shell: app lifecycle (tray, popup window, single instance, autostart)
//! plus the scoped scan, state and preferences commands.
//!
//! Everything about tools and versions lives in the core and the React UI (ADR-0006/0007).
//! The tray is built here at launch and never depends on the webview (ADR-0009).

use std::{
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

use tauri::{
    AppHandle, Emitter, Manager, PhysicalPosition, Runtime, WebviewWindow, WebviewWindowBuilder,
    WindowEvent,
    image::Image,
    menu::{AboutMetadata, CheckMenuItem, Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
};
use tauri_plugin_autostart::ManagerExt;
use tauri_plugin_positioner::{Position, WindowExt};

pub mod autostart;
pub mod badge;
pub mod config_file;
pub mod preferences;
pub mod reveal;
mod saved;
pub mod scan;

use preferences::{Preferences, PreferencesState};
use scan::{FIRST_RUN_TIMEOUT, REFRESH_INTERVAL, SCAN_TIMEOUT, ScanConfig, Scanner, ShellState};

/// Sent to the popup with the full `ShellState` whenever it changes.
const SCAN_UPDATED: &str = "scan-updated";

/// Sent to the popup with the full `PreferencesState` after every preferences query.
const PREFERENCES_UPDATED: &str = "preferences-updated";

/// Where the installer puts the core project, inside the app's resource folder. Must match
/// `bundle.resources` in tauri.conf.json.
const BUNDLED_CORE: &str = "core";

/// The core's Python environment, inside the per-machine app data folder.
const CORE_ENVIRONMENT: &str = "core-env";

/// The saved current and previous scan results, next to the environment.
const SAVED_STATE: &str = "scan-state.json";

/// Window label of the popup, as declared in tauri.conf.json and the capabilities file.
const POPUP: &str = "popup";
const TRAY_ID: &str = "main";
const MENU_REFRESH: &str = "refresh";
const MENU_SHOW: &str = "show-versions";
const MENU_CONFIG: &str = "open-config";
const MENU_AUTOSTART: &str = "start-with-windows";
// About is a predefined native item and raises no menu event, so it has no id here.
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
            on_second_launch(app);
        }))
        .plugin(tauri_plugin_positioner::init())
        // No extra launch arguments: an autostarted app behaves exactly like a manual start.
        .plugin(tauri_plugin_autostart::Builder::new().build())
        .manage(LastBlurHide::default())
        .invoke_handler(tauri::generate_handler![
            get_state,
            get_preferences,
            refresh,
            open_uv_docs,
            open_containing_folder
        ])
        .setup(|app| {
            create_tray(app.handle())?;
            let preferences = Arc::new(Preferences::new(announce_preferences(app.handle())));
            app.manage(preferences.clone());
            // Every scan job queries the preferences first, so each refresh (popup, tray menu,
            // schedule) rereads them, and the launch job learns the update setting early.
            let scanner = Arc::new(
                Scanner::new(scan_config(app.handle())?, announce(app.handle()))
                    .with_preferences(preferences),
            );
            app.manage(scanner.clone());
            // Scans at launch, so the results restored from disk are soon replaced by live
            // ones, then every 30 minutes. The tray is updated as in `start_refresh`.
            let handle = app.handle().clone();
            scan::refresh_every(&scanner, REFRESH_INTERVAL, move |scanner| {
                show_tray_status(&handle, &scanner.state());
            });
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
        first_run_timeout: FIRST_RUN_TIMEOUT,
        // Local for the same reason: a scan describes this machine only.
        state_file: paths.app_local_data_dir()?.join(SAVED_STATE),
    })
}

fn announce<R: Runtime>(app: &AppHandle<R>) -> scan::Notify {
    let app = app.clone();
    Box::new(move |state: &ShellState| {
        // No popup listening yet is normal; it asks with `get_state` when it loads.
        let _ = app.emit(SCAN_UPDATED, state);
    })
}

fn announce_preferences<R: Runtime>(app: &AppHandle<R>) -> preferences::Notify {
    let app = app.clone();
    Box::new(move |state: &PreferencesState| {
        // As with scans: a popup that is not listening asks with `get_preferences`.
        let _ = app.emit(PREFERENCES_UPDATED, state);
    })
}

/// Scans on a background thread so neither IPC nor the tray waits for the core. The tray is
/// updated here, once the scan is over, and not from the state-change callback: that runs
/// while the state is locked, and a tray change waits for the main thread, which may itself
/// be waiting for that lock inside `get_state`. A refresh that was queued because a scan was
/// already running leaves the tray alone: the thread running that scan also runs the queued
/// one and updates the tray when both end, and a snapshot taken now would be stale.
fn start_refresh<R: Runtime>(app: AppHandle<R>, scanner: Arc<Scanner>) {
    thread::spawn(move || {
        if scanner.refresh() {
            show_tray_status(&app, &scanner.state());
        }
    });
}

/// Marks the tray icon with a warning while uv is missing, so the problem is visible
/// without opening the popup, and restores it as soon as a scan finds uv.
fn show_tray_status<R: Runtime>(app: &AppHandle<R>, state: &ShellState) {
    let Some(tray) = app.tray_by_id(TRAY_ID) else {
        return;
    };
    let name = &app.package_info().name;
    let missing = state.uv_missing();
    // Best effort like the window calls: a tray that cannot change must not stop scanning.
    let _ = tray.set_tooltip(Some(if missing {
        format!("{name}: uv was not found")
    } else {
        name.clone()
    }));
    if let Some(icon) = app.default_window_icon() {
        let icon = if missing {
            let (w, h) = (icon.width(), icon.height());
            Image::new_owned(badge::with_warning_badge(icon.rgba(), w, h), w, h)
        } else {
            icon.clone()
        };
        let _ = tray.set_icon(Some(icon));
    }
}

/// The official uv installation page. A fixed address, so the popup cannot make the shell
/// open anything else.
const UV_INSTALL_DOCS: &str = "https://docs.astral.sh/uv/getting-started/installation/";

/// Opens the uv installation page in the default browser. The popup cannot open links on its
/// own (there is deliberately no shell or opener plugin), so this one fixed link has its own
/// command. It only opens a page; VersionBar installs nothing.
#[tauri::command]
fn open_uv_docs() {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // explorer.exe from the Windows folder by full path, like taskkill in scan.rs; it
        // hands the address to the user's default browser.
        if let Some(root) = std::env::var_os("SystemRoot") {
            let _ = std::process::Command::new(std::path::Path::new(&root).join("explorer.exe"))
                .arg(UV_INSTALL_DOCS)
                .creation_flags(scan::CREATE_NO_WINDOW)
                .spawn();
        }
    }
    #[cfg(not(windows))]
    {
        let _ = std::process::Command::new("xdg-open")
            .arg(UV_INSTALL_DOCS)
            .spawn();
    }
}

/// Opens the folder holding one install in Explorer, with the install selected. The error is
/// a sentence for the popup to show.
#[tauri::command]
fn open_containing_folder(path: String) -> Result<(), String> {
    let mut explorer = reveal::explorer_command(&path, std::env::var_os("SystemRoot").as_deref())
        .map_err(|error| error.to_string())?;
    // Not waited for: Explorer hands the request to the running shell and exits on its own,
    // with an exit code that means nothing.
    match explorer.spawn() {
        Ok(_) => Ok(()),
        Err(_) => Err("Explorer could not be started.".to_owned()),
    }
}

/// The popup's view of the scan state: current and previous results plus progress.
#[tauri::command]
fn get_state(scanner: tauri::State<'_, Arc<Scanner>>) -> ShellState {
    scanner.state()
}

/// The popup's view of the preferences: the core's latest `config --json` answer and how the
/// latest query went. Read only; they are reread by `refresh`.
#[tauri::command]
fn get_preferences(preferences: tauri::State<'_, Arc<Preferences>>) -> PreferencesState {
    preferences.state()
}

/// Starts a scan, preceded by a preferences query, and returns at once; the results arrive as
/// `preferences-updated` and `scan-updated` events. While a scan is already running it queues
/// one more scan after it, shared with any other requests made during that scan.
#[tauri::command]
fn refresh<R: Runtime>(app: AppHandle<R>, scanner: tauri::State<'_, Arc<Scanner>>) {
    start_refresh(app, scanner.inner().clone());
}

/// Opens the config file from the tray menu, creating the starter file first if there is none.
/// The path is whatever the latest preferences query reported, read now, so nothing about the
/// config is cached here beyond that path. The menu has no place to show an error, so failures
/// go to stderr; an unknown path also starts a refresh, whose preferences query learns it.
fn open_config_file<R: Runtime>(app: &AppHandle<R>) {
    let path = app
        .try_state::<Arc<Preferences>>()
        .and_then(|preferences| preferences.config_path());
    let opened = config_file::open_command(
        path.as_deref(),
        config_file::STARTER_CONFIG,
        std::env::var_os("SystemRoot").as_deref(),
    )
    .and_then(|mut explorer| {
        // Not waited for, as in `open_containing_folder`.
        explorer
            .spawn()
            .map(drop)
            .map_err(|_| config_file::ConfigError::CannotStart)
    });
    if let Err(error) = opened {
        eprintln!("Open config file: {error}");
        if path.is_none()
            && let Some(scanner) = app.try_state::<Arc<Scanner>>()
        {
            start_refresh(app.clone(), scanner.inner().clone());
        }
    }
}

/// Start with Windows: flips autostart and sets the check mark to the state read back
/// afterwards. Windows flips a check item's mark by itself when it is clicked, so the mark is
/// always set here, also when the change failed, to keep it showing the real state.
fn toggle_autostart<R: Runtime>(app: &AppHandle<R>, item: &CheckMenuItem<R>) {
    let enabled = autostart::toggle(&*app.autolaunch());
    let _ = item.set_checked(enabled);
}

fn create_tray<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    // Kept for the menu handler, which sets its check mark after each toggle.
    let autostart_item = CheckMenuItem::with_id(
        app,
        MENU_AUTOSTART,
        "Start with Windows",
        true,
        autostart::read_checked(&*app.autolaunch()),
        None::<&str>,
    )?;
    // Show versions is always in the menu: Linux trays do not report left-clicks (ADR-0009).
    let menu = Menu::with_items(
        app,
        &[
            &MenuItem::with_id(app, MENU_REFRESH, "Refresh", true, None::<&str>)?,
            &MenuItem::with_id(app, MENU_SHOW, "Show versions", true, None::<&str>)?,
            &MenuItem::with_id(app, MENU_CONFIG, "Open config file", true, None::<&str>)?,
            &autostart_item,
            // Name and version come from the app's own metadata (tauri.conf.json and Cargo.toml),
            // never from literals here.
            &PredefinedMenuItem::about(
                app,
                Some(&format!("About {}", app.package_info().name)),
                Some(AboutMetadata {
                    name: Some(app.package_info().name.clone()),
                    version: Some(app.package_info().version.to_string()),
                    ..Default::default()
                }),
            )?,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(app, MENU_QUIT, "Quit", true, None::<&str>)?,
        ],
    )?;

    let mut tray = TrayIconBuilder::with_id(TRAY_ID)
        .tooltip(&app.package_info().name)
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(move |app, event| match event.id().as_ref() {
            // Talks to the scanner directly, never to the popup, so it works before the
            // popup has ever loaded and while its page is broken (spec story 57). The
            // scanner is registered right after the tray, so it is only missing in the
            // moment before setup finishes.
            MENU_REFRESH => {
                if let Some(scanner) = app.try_state::<Arc<Scanner>>() {
                    start_refresh(app.clone(), scanner.inner().clone());
                }
            }
            MENU_SHOW => show_popup(app),
            MENU_CONFIG => open_config_file(app),
            MENU_AUTOSTART => toggle_autostart(app, &autostart_item),
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

/// The popup window, recreated from its tauri.conf.json entry when it is gone, so a popup
/// whose window was destroyed comes back on the next Show versions or tray click instead of
/// leaving the tray with nothing to show (ADR-0009).
fn popup<R: Runtime>(app: &AppHandle<R>) -> Option<WebviewWindow<R>> {
    if let Some(window) = app.get_webview_window(POPUP) {
        return Some(window);
    }
    let config = app
        .config()
        .app
        .windows
        .iter()
        .find(|window| window.label == POPUP)?;
    WebviewWindowBuilder::from_config(app, config)
        .and_then(|builder| builder.build())
        .inspect_err(|error| eprintln!("Could not recreate the popup: {error}"))
        .ok()
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

/// What the running app does when it is launched again. The single-instance plugin has already
/// made the new process exit before it built anything, so there is never a second tray; this
/// only brings up the existing popup.
pub fn on_second_launch<R: Runtime>(app: &AppHandle<R>) {
    show_popup(app);
}

/// Shows the popup above the tray and focuses it, recreating it first if its window is gone.
pub fn show_popup<R: Runtime>(app: &AppHandle<R>) {
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
