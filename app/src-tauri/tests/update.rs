//! The updater, driven through `Updater` with a fake update source in place of the signed feed
//! (no network) and the real preferences, read through `Scanner` with a fake `uv` that answers
//! `config --json` from a file the test writes (AGENTS.md "Testing": the Rust seam).

use std::{
    fs,
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
    time::{Duration, Instant},
};

use serde_json::{Value, json};
use tray_shell::{
    preferences::{Preferences, PreferencesState},
    scan::{ScanConfig, Scanner, ShellState},
    update::{UpdateSource, UpdateState, Updater, check_on_schedule},
};

fn fixture(name: &str) -> String {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../src/test/fixtures")
        .join(name);
    fs::read_to_string(&path).unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()))
}

fn scratch(name: &str) -> PathBuf {
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    let dir = std::env::temp_dir().join(format!(
        "tray-shell-update-{}-{}-{name}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::SeqCst)
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    dir
}

/// A fake uv: `config` prints `config.json`, `list` prints a real scan.
#[cfg(windows)]
fn write_fake(dir: &Path) -> PathBuf {
    let script = format!(
        "@echo off\r\n\
         if \"%~9\"==\"config\" (type \"{d}\\config.json\") else (type \"{d}\\scan.json\")\r\n\
         exit /b 0\r\n",
        d = dir.display()
    );
    let path = dir.join("uv.cmd");
    fs::write(&path, script).unwrap();
    path
}

#[cfg(not(windows))]
fn write_fake(dir: &Path) -> PathBuf {
    use std::os::unix::fs::PermissionsExt;
    let script = format!(
        "#!/bin/sh\n\
         if [ \"$9\" = config ]; then cat '{d}/config.json'; else cat '{d}/scan.json'; fi\n",
        d = dir.display()
    );
    let path = dir.join("uv");
    fs::write(&path, script).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    path
}

/// What the fake feed answers and how often it was asked.
struct Feed {
    offer: Mutex<Result<Option<String>, String>>,
    install_result: Mutex<Result<(), String>>,
    checks: AtomicUsize,
    installs: AtomicUsize,
    /// While true, a check waits (a stalled request) before answering.
    held: AtomicBool,
}

impl Feed {
    fn new() -> Arc<Self> {
        Arc::new(Feed {
            offer: Mutex::new(Ok(None)),
            install_result: Mutex::new(Ok(())),
            checks: AtomicUsize::new(0),
            installs: AtomicUsize::new(0),
            held: AtomicBool::new(false),
        })
    }

    fn offers(&self, version: &str) {
        *self.offer.lock().unwrap() = Ok(Some(version.to_owned()));
    }

    fn fails_checks(&self, message: &str) {
        *self.offer.lock().unwrap() = Err(message.to_owned());
    }

    fn fails_installs(&self, message: &str) {
        *self.install_result.lock().unwrap() = Err(message.to_owned());
    }

    fn hold_checks(&self) {
        self.held.store(true, Ordering::SeqCst);
    }

    fn release_checks(&self) {
        self.held.store(false, Ordering::SeqCst);
    }

    fn checks(&self) -> usize {
        self.checks.load(Ordering::SeqCst)
    }

    fn installs(&self) -> usize {
        self.installs.load(Ordering::SeqCst)
    }
}

struct FakeSource(Arc<Feed>);

impl UpdateSource for FakeSource {
    fn check(&self) -> Result<Option<String>, String> {
        self.0.checks.fetch_add(1, Ordering::SeqCst);
        while self.0.held.load(Ordering::SeqCst) {
            std::thread::sleep(Duration::from_millis(10));
        }
        self.0.offer.lock().unwrap().clone()
    }

    fn install(&self) -> Result<(), String> {
        self.0.installs.fetch_add(1, Ordering::SeqCst);
        self.0.install_result.lock().unwrap().clone()
    }
}

/// The scanner, preferences and updater wired as the app wires them.
struct App {
    dir: PathBuf,
    scanner: Scanner,
    updater: Arc<Updater>,
    feed: Arc<Feed>,
    events: Arc<Mutex<Vec<Value>>>,
}

const DAY: Duration = Duration::from_secs(24 * 60 * 60);

fn app(name: &str, interval: Duration) -> App {
    let dir = scratch(name);
    let uv = write_fake(&dir);
    fs::write(dir.join("scan.json"), fixture("list-windows.json")).unwrap();
    let config = ScanConfig {
        find_uv: Box::new(move || Some(uv.clone())),
        project: dir.join("core"),
        environment: dir.join("core-env"),
        state_file: dir.join("scan-state.json"),
        timeout: Duration::from_secs(30),
        first_run_timeout: Duration::from_secs(30),
    };
    let preferences = Arc::new(Preferences::new(Box::new(|_: &PreferencesState| {})));
    let scanner =
        Scanner::new(config, Box::new(|_: &ShellState| {})).with_preferences(preferences.clone());
    let feed = Feed::new();
    let events: Arc<Mutex<Vec<Value>>> = Arc::default();
    let sink = events.clone();
    let updater = Arc::new(Updater::new(
        Box::new(FakeSource(feed.clone())),
        preferences,
        interval,
        Box::new(move |state: &UpdateState| sink.lock().unwrap().push(wire(state))),
    ));
    App {
        dir,
        scanner,
        updater,
        feed,
        events,
    }
}

impl App {
    /// Rewrites the config answer and runs a refresh, whose preferences query reads it.
    fn preferences(&self, fixture_name: &str) {
        fs::write(self.dir.join("config.json"), fixture(fixture_name)).unwrap();
        self.scanner.refresh();
    }

    fn update_on(&self) {
        self.preferences("config-windows-defaults.json");
    }

    fn update_off(&self) {
        self.preferences("config-windows-update-off.json");
    }

    fn state(&self) -> Value {
        wire(&self.updater.state())
    }
}

/// The update state exactly as the popup receives it over IPC.
fn wire(state: &UpdateState) -> Value {
    serde_json::to_value(state).unwrap()
}

fn nothing_offered() -> Value {
    json!({"version": null, "installing": false, "error": null})
}

fn offered(version: &str) -> Value {
    json!({"version": version, "installing": false, "error": null})
}

#[test]
fn nothing_is_checked_before_the_first_preferences_answer() {
    let app = app("before-prefs", DAY);
    app.feed.offers("0.2.0");

    app.updater.check_if_due();

    assert_eq!(app.feed.checks(), 0);
    assert_eq!(app.state(), nothing_offered());
}

#[test]
fn with_update_checks_on_a_check_offers_the_newer_version() {
    let app = app("offer", DAY);
    app.feed.offers("0.2.0");
    app.update_on();

    app.updater.check_if_due();

    assert_eq!(app.feed.checks(), 1);
    assert_eq!(app.state(), offered("0.2.0"));
    assert_eq!(app.events.lock().unwrap().last(), Some(&offered("0.2.0")));
}

#[test]
fn a_check_that_finds_no_update_offers_nothing() {
    let app = app("none", DAY);
    app.update_on();

    app.updater.check_if_due();

    assert_eq!(app.feed.checks(), 1);
    assert_eq!(app.state(), nothing_offered());
}

#[test]
fn with_update_checks_off_the_feed_is_never_asked() {
    let app = app("off", Duration::ZERO);
    app.feed.offers("0.2.0");
    app.update_off();

    app.updater.check_if_due();
    app.updater.check_if_due();

    assert_eq!(app.feed.checks(), 0);
    assert_eq!(app.state(), nothing_offered());
}

#[test]
fn the_feed_is_asked_again_only_once_the_interval_has_passed() {
    let daily = app("daily", DAY);
    daily.update_on();
    daily.updater.check_if_due();
    daily.updater.check_if_due();
    assert_eq!(daily.feed.checks(), 1);

    let due = app("due", Duration::ZERO);
    due.update_on();
    due.updater.check_if_due();
    due.updater.check_if_due();
    assert_eq!(due.feed.checks(), 2);
}

#[test]
fn a_failed_check_shows_nothing_and_keeps_an_earlier_offer() {
    let fresh = app("check-fails", Duration::ZERO);
    fresh
        .feed
        .fails_checks("Could not fetch a valid release JSON from the remote");
    fresh.update_on();
    fresh.updater.check_if_due();
    assert_eq!(fresh.state(), nothing_offered());

    let earlier = app("check-fails-later", Duration::ZERO);
    earlier.feed.offers("0.2.0");
    earlier.update_on();
    earlier.updater.check_if_due();
    earlier
        .feed
        .fails_checks("Could not fetch a valid release JSON from the remote");
    earlier.updater.check_if_due();
    assert_eq!(earlier.feed.checks(), 2);
    assert_eq!(earlier.state(), offered("0.2.0"));
}

#[test]
fn turning_update_checks_off_stops_checks_and_turning_them_on_resumes_them() {
    let app = app("toggle", Duration::ZERO);
    app.feed.offers("0.2.0");
    app.update_on();
    app.updater.check_if_due();
    assert_eq!(app.feed.checks(), 1);

    app.update_off();
    app.updater.check_if_due();
    assert_eq!(app.feed.checks(), 1);
    assert_eq!(
        app.state(),
        nothing_offered(),
        "no offer while checks are off"
    );

    app.update_on();
    app.updater.check_if_due();
    assert_eq!(app.feed.checks(), 2);
    assert_eq!(app.state(), offered("0.2.0"));
}

#[test]
fn turning_update_checks_back_on_shows_the_known_offer_without_asking_again() {
    let app = app("toggle-daily", DAY);
    app.feed.offers("0.2.0");
    app.update_on();
    app.updater.check_if_due();

    app.update_off();
    app.updater.check_if_due();
    assert_eq!(app.state(), nothing_offered());

    app.update_on();
    app.updater.check_if_due();
    assert_eq!(app.state(), offered("0.2.0"));
    assert_eq!(
        app.feed.checks(),
        1,
        "still within the 24 h since the last check"
    );
}

#[test]
fn a_failed_check_counts_as_a_check_until_the_interval_has_passed() {
    let app = app("check-fails-daily", DAY);
    app.feed
        .fails_checks("Could not fetch a valid release JSON from the remote");
    app.update_on();

    app.updater.check_if_due();
    app.updater.check_if_due();

    assert_eq!(app.feed.checks(), 1);
}

/// Runs `check_if_due` on its own thread and waits until the fake feed has been asked, so the
/// check is stalled inside the request when this returns.
fn stalled_check(app: &App) -> std::thread::JoinHandle<()> {
    let before = app.feed.checks();
    app.feed.hold_checks();
    let updater = app.updater.clone();
    let check = std::thread::spawn(move || updater.check_if_due());
    let deadline = Instant::now() + Duration::from_secs(10);
    while app.feed.checks() == before && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(app.feed.checks(), before + 1, "the check never started");
    check
}

#[test]
fn a_stalled_check_never_holds_up_a_confirmed_install_nor_takes_its_offer() {
    let app = app("stalled-install", Duration::ZERO);
    app.feed.offers("0.2.0");
    app.update_on();
    app.updater.check_if_due();
    let check = stalled_check(&app);

    let message = "The update could not be installed: error sending request";
    app.feed.fails_installs(message);
    assert!(
        !app.updater.install(),
        "install ran and failed while the check was stalled"
    );
    assert_eq!(app.feed.installs(), 1);

    // The install failed while the check was stalled and the offer was still shown.
    assert_eq!(
        app.state(),
        json!({"version": "0.2.0", "installing": false, "error": message})
    );

    // The stalled check then finds nothing: the offer is gone, and so is the failed install.
    *app.feed.offer.lock().unwrap() = Ok(None);
    app.feed.release_checks();
    check.join().unwrap();
    assert_eq!(app.state(), nothing_offered());
}

#[test]
fn a_check_that_finishes_while_installing_leaves_the_banner_alone() {
    let app = app("stalled-during-install", Duration::ZERO);
    app.feed.offers("0.2.0");
    app.update_on();
    app.updater.check_if_due();
    let check = stalled_check(&app);
    // A successful install leaves `installing` set until the app restarts.
    assert!(app.updater.install());

    *app.feed.offer.lock().unwrap() = Ok(None);
    app.feed.release_checks();
    check.join().unwrap();

    assert_eq!(
        app.state(),
        json!({"version": "0.2.0", "installing": true, "error": null})
    );
}

#[test]
fn an_answer_that_arrives_after_checks_were_turned_off_is_not_shown() {
    let app = app("stalled-disable", Duration::ZERO);
    app.update_on();
    let check = stalled_check(&app);

    app.update_off();
    app.feed.offers("0.2.0");
    app.feed.release_checks();
    check.join().unwrap();

    assert_eq!(app.state(), nothing_offered());
}

#[test]
fn nothing_is_installed_without_an_offer() {
    let app = app("no-offer", DAY);
    app.update_on();
    app.updater.check_if_due();

    assert!(!app.updater.install());
    assert_eq!(app.feed.installs(), 0);
}

#[test]
fn a_confirmed_install_runs_once_and_reports_success() {
    let app = app("install", DAY);
    app.feed.offers("0.2.0");
    app.update_on();
    app.updater.check_if_due();

    assert!(app.updater.install());

    assert_eq!(app.feed.installs(), 1);
    assert_eq!(
        app.state(),
        json!({"version": "0.2.0", "installing": true, "error": null})
    );
}

#[test]
fn a_signature_failure_shows_the_error_and_keeps_the_offer_and_the_scan() {
    let app = app("signature", DAY);
    app.feed.offers("0.2.0");
    app.update_on();
    app.updater.check_if_due();
    let scan_before = serde_json::to_value(app.scanner.state()).unwrap();
    let message = "The update could not be installed: the signature does not match.";
    app.feed.fails_installs(message);

    assert!(!app.updater.install());

    assert_eq!(
        app.state(),
        json!({"version": "0.2.0", "installing": false, "error": message})
    );
    let events = app.events.lock().unwrap().clone();
    assert!(
        events
            .iter()
            .any(|state| state["installing"] == json!(true)),
        "the popup hears that the install started: {events:?}"
    );
    assert_eq!(
        serde_json::to_value(app.scanner.state()).unwrap(),
        scan_before
    );

    // Retry: the same offer can be installed again, and a new attempt clears the old error.
    *app.feed.install_result.lock().unwrap() = Ok(());
    assert!(app.updater.install());
    assert_eq!(app.feed.installs(), 2);
    assert_eq!(app.state()["error"], Value::Null);
}

#[test]
fn a_failed_install_is_cleared_once_a_later_check_finds_nothing_on_offer() {
    let app = app("offer-withdrawn", Duration::ZERO);
    app.feed.offers("0.2.0");
    app.update_on();
    app.updater.check_if_due();
    app.feed
        .fails_installs("The update could not be installed.");
    assert!(!app.updater.install());
    assert_eq!(
        app.state()["error"],
        json!("The update could not be installed.")
    );

    // The release is gone, so Retry would only fail with "no longer available".
    *app.feed.offer.lock().unwrap() = Ok(None);
    app.updater.check_if_due();

    assert_eq!(app.state(), nothing_offered());
}

#[test]
fn the_schedule_checks_as_soon_as_the_first_preferences_answer_allows_it() {
    let app = app("schedule", DAY);
    app.feed.offers("0.2.0");
    let schedule = check_on_schedule(&app.updater, DAY);

    // The schedule's first look found no answer yet, so it waits to be woken.
    std::thread::sleep(Duration::from_millis(200));
    assert_eq!(app.feed.checks(), 0);

    app.update_on();
    app.updater.wake();
    let deadline = Instant::now() + Duration::from_secs(10);
    while app.feed.checks() == 0 && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    assert_eq!(app.feed.checks(), 1);
    assert_eq!(app.state(), offered("0.2.0"));

    // The thread ends once the updater is gone, as in `refresh_every`.
    let App { updater, .. } = app;
    drop(updater);
    assert!(schedule.join().is_ok());
}
