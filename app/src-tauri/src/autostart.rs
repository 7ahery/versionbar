//! The Start with Windows menu item. The check mark always mirrors what the system reports:
//! nothing about autostart is stored here, so a change made outside the app (Task Manager's
//! Startup apps page, for example) shows up the next time the state is read.

use tauri_plugin_autostart::AutoLaunchManager;

/// Turning autostart on and off, as the official autostart plugin does it. A trait so the menu
/// logic can be tested without touching the registry.
pub trait Autostart {
    fn is_enabled(&self) -> Result<bool, String>;
    fn enable(&self) -> Result<(), String>;
    fn disable(&self) -> Result<(), String>;
}

impl Autostart for AutoLaunchManager {
    fn is_enabled(&self) -> Result<bool, String> {
        AutoLaunchManager::is_enabled(self).map_err(|error| error.to_string())
    }

    fn enable(&self) -> Result<(), String> {
        AutoLaunchManager::enable(self).map_err(|error| error.to_string())
    }

    fn disable(&self) -> Result<(), String> {
        AutoLaunchManager::disable(self).map_err(|error| error.to_string())
    }
}

/// Whether the menu item should show checked, read now from the system: used when the menu is
/// built and after every toggle. The app never enables autostart by itself, so a
/// fresh install reads as off. An unreadable state also shows as off: the menu has nowhere to
/// show an error, so it goes to stderr.
pub fn read_checked(autostart: &dyn Autostart) -> bool {
    autostart.is_enabled().unwrap_or_else(|error| {
        eprintln!("Start with Windows: could not read the current state: {error}");
        false
    })
}

/// Flips autostart and returns the state to show afterwards, read back from the system rather
/// than assumed, so a failed change leaves the check mark telling the truth. When the current
/// state cannot be read, nothing is changed: there is no way to know which way to flip.
pub fn toggle(autostart: &dyn Autostart) -> bool {
    let changed = match autostart.is_enabled() {
        Ok(true) => autostart.disable(),
        Ok(false) => autostart.enable(),
        Err(error) => Err(error),
    };
    if let Err(error) = changed {
        eprintln!("Start with Windows: {error}");
    }
    read_checked(autostart)
}
