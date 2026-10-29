//! App updates (spec stories 34 and 69-71, docs/app/updates.md): checks the signed feed at
//! startup and every 24 hours while the preferences allow it, and installs only after the user
//! confirms in the popup.
//!
//! Rust owns the whole flow; the webview holds no updater permission. It reads the state below
//! and confirms through one command without arguments.

use std::{
    sync::{Arc, Condvar, Mutex},
    thread,
    time::{Duration, Instant},
};

use serde::Serialize;

use crate::preferences::Preferences;

/// How often the feed is asked while the app runs (spec story 69).
pub const CHECK_INTERVAL: Duration = Duration::from_secs(24 * 60 * 60);

/// How long the schedule sleeps when nothing wakes it. Being woken after every preferences
/// query is what normally drives it; this only bounds the wait if those stop.
pub const SCHEDULE_POLL: Duration = Duration::from_secs(60 * 60);

/// Where updates come from: the signed feed in the app, a fake in tests.
pub trait UpdateSource: Send + Sync {
    /// Asks the feed once. `Ok(Some(version))` when it offers a newer release, `Ok(None)` when
    /// it offers none.
    fn check(&self) -> Result<Option<String>, String>;

    /// Downloads the release the last check offered, verifies its signature and starts its
    /// installer. The error is a sentence for the popup.
    fn install(&self) -> Result<(), String>;
}

/// Called with the new state whenever it changes; the app turns this into the
/// `update-updated` event.
pub type Notify = Box<dyn Fn(&UpdateState) + Send + Sync>;

/// What the popup gets over IPC (`get_update` and the `update-updated` event).
#[derive(Clone, Debug, Default, Serialize)]
pub struct UpdateState {
    /// The newer version the feed offers; null when there is none or checks are off.
    version: Option<String>,
    /// True from the user's confirmation until the install fails (or the app restarts).
    installing: bool,
    /// Why the last confirmed install failed. Failed checks are never shown (DEV-10).
    error: Option<String>,
}

pub struct Updater {
    source: Box<dyn UpdateSource>,
    preferences: Arc<Preferences>,
    interval: Duration,
    known: Mutex<Known>,
    /// Held across every call into the source, so a check never replaces the offer while it
    /// is being installed.
    busy: Mutex<()>,
    notify: Notify,
    wake: Arc<Wake>,
}

#[derive(Default)]
struct Known {
    state: UpdateState,
    /// When the feed was last asked, whatever it answered; None until the first check.
    last_check: Option<Instant>,
}

impl Updater {
    pub fn new(
        source: Box<dyn UpdateSource>,
        preferences: Arc<Preferences>,
        interval: Duration,
        notify: Notify,
    ) -> Self {
        Updater {
            source,
            preferences,
            interval,
            known: Mutex::default(),
            busy: Mutex::new(()),
            notify,
            wake: Arc::default(),
        }
    }

    pub fn state(&self) -> UpdateState {
        self.known.lock().unwrap().state.clone()
    }

    /// Asks the feed if update checks are on and the interval has passed since the last check.
    /// Preferences that are not known yet count as off (DEC-22), so the first check waits for
    /// the launch job's query. A failed check is quiet: it keeps what was known and counts as
    /// a check, so it is retried at the next scheduled one.
    pub fn check_if_due(&self) {
        let _busy = self.busy.lock().unwrap();
        if !self.preferences.update_check() {
            // An offer the user can no longer act on without going online stays hidden while
            // checks are off; the next allowed check brings it back. An install the user already
            // confirmed keeps its offer.
            self.change(|known| !known.state.installing && known.state.version.take().is_some());
            return;
        }
        {
            let known = self.known.lock().unwrap();
            let due = known
                .last_check
                .is_none_or(|at| at.elapsed() >= self.interval);
            if known.state.installing || !due {
                return;
            }
        }
        let answer = self.source.check();
        self.change(|known| {
            known.last_check = Some(Instant::now());
            match answer {
                Ok(version) if version != known.state.version => {
                    known.state.version = version;
                    true
                }
                Ok(_) => false,
                Err(message) => {
                    eprintln!("Update check failed: {message}");
                    false
                }
            }
        });
    }

    /// Installs the offered update after the user confirmed it. Returns true when the
    /// installer was started, after which the caller restarts the app. A failure is kept in
    /// the state with the offer, so the popup can show it and offer Retry.
    pub fn install(&self) -> bool {
        let started = self.change(|known| {
            let ready = known.state.version.is_some() && !known.state.installing;
            if ready {
                known.state.installing = true;
                known.state.error = None;
            }
            ready
        });
        if !started {
            return false;
        }
        let _busy = self.busy.lock().unwrap();
        match self.source.install() {
            Ok(()) => true,
            Err(message) => {
                self.change(|known| {
                    known.state.installing = false;
                    known.state.error = Some(message);
                    true
                });
                false
            }
        }
    }

    /// Makes the schedule look again now, for example because the preferences were reread.
    pub fn wake(&self) {
        self.wake.signal();
    }

    /// Applies `change` under the lock and announces the new state if it returns true.
    fn change(&self, change: impl FnOnce(&mut Known) -> bool) -> bool {
        let mut known = self.known.lock().unwrap();
        let changed = change(&mut known);
        if changed {
            // Announced while still locked, so listeners see the states in order.
            (self.notify)(&known.state);
        }
        changed
    }
}

impl Drop for Updater {
    /// Lets a waiting schedule notice at once that the updater is gone.
    fn drop(&mut self) {
        self.wake.signal();
    }
}

#[derive(Default)]
struct Wake {
    woken: Mutex<bool>,
    signal: Condvar,
}

impl Wake {
    fn signal(&self) {
        *self.woken.lock().unwrap() = true;
        self.signal.notify_all();
    }

    fn wait(&self, timeout: Duration) {
        let woken = self.woken.lock().unwrap();
        let (mut woken, _) = self
            .signal
            .wait_timeout_while(woken, timeout, |woken| !*woken)
            .unwrap();
        *woken = false;
    }
}

/// The real source: Tauri's updater plugin, reading the endpoint and public key from
/// `plugins.updater` in tauri.conf.json. The plugin verifies the download against that key
/// before it starts the installer.
#[cfg(desktop)]
pub struct PluginSource<R: tauri::Runtime> {
    app: tauri::AppHandle<R>,
    /// The release the last check offered; installing needs the plugin's own description of it.
    found: Mutex<Option<tauri_plugin_updater::Update>>,
}

#[cfg(desktop)]
impl<R: tauri::Runtime> PluginSource<R> {
    pub fn new(app: tauri::AppHandle<R>) -> Self {
        PluginSource {
            app,
            found: Mutex::default(),
        }
    }
}

#[cfg(desktop)]
impl<R: tauri::Runtime> UpdateSource for PluginSource<R> {
    fn check(&self) -> Result<Option<String>, String> {
        use tauri_plugin_updater::UpdaterExt;
        // Anything but a 204 or a valid feed is an error here, including the 404 while a
        // release is still building (DEV-10); the caller keeps those quiet.
        let updater = self.app.updater().map_err(|error| error.to_string())?;
        let update =
            tauri::async_runtime::block_on(updater.check()).map_err(|error| error.to_string())?;
        let version = update.as_ref().map(|update| update.version.clone());
        *self.found.lock().unwrap() = update;
        Ok(version)
    }

    fn install(&self) -> Result<(), String> {
        let found = self.found.lock().unwrap();
        let update = found
            .as_ref()
            .ok_or_else(|| "The update is no longer available.".to_owned())?;
        // On Windows this exits the app once the installer has started; the installer restarts
        // it when done.
        tauri::async_runtime::block_on(update.download_and_install(|_, _| {}, || {}))
            .map_err(|error| format!("The update could not be installed: {error}"))
    }
}

/// Checks whenever woken (after each preferences query) and at least every `poll`, on a thread
/// of its own; `check_if_due` decides whether the feed is really asked. The thread holds the
/// updater only while checking and stops once every other handle on it is gone, which only
/// happens in tests.
pub fn check_on_schedule(updater: &Arc<Updater>, poll: Duration) -> thread::JoinHandle<()> {
    let wake = updater.wake.clone();
    let updater = Arc::downgrade(updater);
    thread::spawn(move || {
        loop {
            let Some(strong) = updater.upgrade() else {
                return;
            };
            strong.check_if_due();
            drop(strong);
            wake.wait(poll);
        }
    })
}
