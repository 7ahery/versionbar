//! The preferences query, driven through `Scanner` with a fake `uv` in place of the real one
//! (AGENTS.md "Testing": the Rust seam). The fake answers `config --json` from files the test
//! writes, so a test can change the answer between reads, and records how it was called.

use std::{
    fs,
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicUsize, Ordering},
    },
    time::Duration,
};

use serde_json::{Value, json};
use tray_shell::{
    preferences::{Preferences, PreferencesState},
    scan::{ScanConfig, Scanner, ShellState},
};

fn fixture(name: &str) -> String {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../src/test/fixtures")
        .join(name);
    fs::read_to_string(&path).unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()))
}

/// Real `versionbar config --json` output with no config file: every default applies.
fn defaults() -> String {
    fixture("config-windows-defaults.json")
}

/// Real output for a config file that sets `update_check = false`.
fn update_off() -> String {
    fixture("config-windows-update-off.json")
}

/// Real output (exit code 3) for a config file whose `update_check` is not a boolean.
fn invalid() -> String {
    fixture("config-windows-invalid.json")
}

fn parsed(text: &str) -> Value {
    serde_json::from_str(text).unwrap()
}

fn scratch(name: &str) -> PathBuf {
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    let dir = std::env::temp_dir().join(format!(
        "tray-shell-prefs-{}-{}-{name}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::SeqCst)
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    dir
}

/// A fake uv that prints a real scan for `list` and, for `config`, prints `config.json` (if
/// present) and exits with the code in `config-exit.txt` (default 0), or hangs while
/// `config-hang` exists.
struct Rig {
    dir: PathBuf,
    uv: PathBuf,
    /// Lets a test take uv away between reads.
    uv_present: Arc<Mutex<bool>>,
}

impl Rig {
    fn new(name: &str) -> Self {
        let dir = scratch(name);
        let uv = write_fake(&dir);
        fs::write(dir.join("scan.json"), fixture("list-windows.json")).unwrap();
        Rig {
            dir,
            uv,
            uv_present: Arc::new(Mutex::new(true)),
        }
    }

    /// The next `config --json` prints `output` and exits with `code`.
    fn answer(&self, output: &str, code: i32) {
        fs::write(self.dir.join("config.json"), output).unwrap();
        fs::write(self.dir.join("config-exit.txt"), code.to_string()).unwrap();
    }

    fn hang(&self) {
        fs::write(self.dir.join("config-hang"), "").unwrap();
    }

    fn remove_uv(&self) {
        *self.uv_present.lock().unwrap() = false;
    }

    fn config(&self, timeout: Duration) -> ScanConfig {
        let uv = self.uv.clone();
        let present = self.uv_present.clone();
        ScanConfig {
            find_uv: Box::new(move || (*present.lock().unwrap()).then(|| uv.clone())),
            project: self.dir.join("core"),
            environment: self.dir.join("core-env"),
            state_file: self.dir.join("scan-state.json"),
            timeout,
            first_run_timeout: timeout,
        }
    }

    fn lines(&self, file: &str) -> Vec<String> {
        fs::read_to_string(self.dir.join(file))
            .unwrap_or_default()
            .lines()
            .map(|line| line.trim().to_owned())
            .filter(|line| !line.is_empty())
            .collect()
    }

    /// Which core command each uv call ran, in order.
    fn commands(&self) -> Vec<String> {
        self.lines("calls.txt")
    }
}

#[cfg(windows)]
fn write_fake(dir: &Path) -> PathBuf {
    let script = format!(
        "@echo off\r\n\
         echo %~9>>\"{d}\\calls.txt\"\r\n\
         if not \"%~9\"==\"config\" goto list\r\n\
         del \"{d}\\config-args.txt\" 2>nul\r\n\
         for %%a in (%*) do echo %%~a>>\"{d}\\config-args.txt\"\r\n\
         echo %UV_PROJECT_ENVIRONMENT%>\"{d}\\config-env.txt\"\r\n\
         echo %PYTHONPYCACHEPREFIX%>>\"{d}\\config-env.txt\"\r\n\
         if exist \"{d}\\config-hang\" ping -n 60 127.0.0.1 >nul\r\n\
         if exist \"{d}\\config.json\" type \"{d}\\config.json\"\r\n\
         set CODE=0\r\n\
         if exist \"{d}\\config-exit.txt\" set /p CODE=<\"{d}\\config-exit.txt\"\r\n\
         exit /b %CODE%\r\n\
         :list\r\n\
         type \"{d}\\scan.json\"\r\n\
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
         echo \"$9\" >> '{d}/calls.txt'\n\
         if [ \"$9\" = config ]; then\n\
           rm -f '{d}/config-args.txt'\n\
           for a in \"$@\"; do echo \"$a\" >> '{d}/config-args.txt'; done\n\
           echo \"$UV_PROJECT_ENVIRONMENT\" > '{d}/config-env.txt'\n\
           echo \"$PYTHONPYCACHEPREFIX\" >> '{d}/config-env.txt'\n\
           if [ -e '{d}/config-hang' ]; then sleep 60; fi\n\
           if [ -e '{d}/config.json' ]; then cat '{d}/config.json'; fi\n\
           code=0\n\
           if [ -e '{d}/config-exit.txt' ]; then code=$(cat '{d}/config-exit.txt'); fi\n\
           exit $code\n\
         fi\n\
         cat '{d}/scan.json'\n",
        d = dir.display()
    );
    let path = dir.join("uv");
    fs::write(&path, script).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    path
}

const TIMEOUT: Duration = Duration::from_secs(30);

/// The scanner and its preferences, wired as the app wires them, with every
/// `preferences-updated` payload recorded.
struct App {
    scanner: Scanner,
    preferences: Arc<Preferences>,
    events: Arc<Mutex<Vec<Value>>>,
}

fn app(config: ScanConfig) -> App {
    let events: Arc<Mutex<Vec<Value>>> = Arc::default();
    let sink = events.clone();
    let preferences = Arc::new(Preferences::new(Box::new(
        move |state: &PreferencesState| {
            sink.lock().unwrap().push(wire(state));
        },
    )));
    let scanner =
        Scanner::new(config, Box::new(|_: &ShellState| {})).with_preferences(preferences.clone());
    App {
        scanner,
        preferences,
        events,
    }
}

/// The preferences exactly as the popup receives them over IPC.
fn wire(state: &PreferencesState) -> Value {
    serde_json::to_value(state).unwrap()
}

#[test]
fn before_any_query_nothing_is_known_and_updates_are_off() {
    let rig = Rig::new("empty");
    let app = app(rig.config(TIMEOUT));

    assert_eq!(
        wire(&app.preferences.state()),
        json!({"config": null, "outcome": null})
    );
    assert!(!app.preferences.update_check());
    assert_eq!(app.preferences.config_path(), None);
}

#[test]
fn a_refresh_queries_preferences_with_fixed_arguments_before_scanning() {
    let rig = Rig::new("argv");
    rig.answer(&defaults(), 0);
    let app = app(rig.config(TIMEOUT));

    app.scanner.refresh();

    assert_eq!(rig.commands(), ["config", "list"]);
    let project = rig.dir.join("core").display().to_string();
    assert_eq!(
        rig.lines("config-args.txt"),
        [
            "run",
            "--frozen",
            "--no-dev",
            "--managed-python",
            "--project",
            project.as_str(),
            "--",
            "versionbar",
            "config",
            "--json",
        ]
    );
    // The same environment as the scan, so both share one core-env.
    assert_eq!(
        rig.lines("config-env.txt"),
        [
            rig.dir.join("core-env").display().to_string(),
            rig.dir
                .join("core-env")
                .join("pycache")
                .display()
                .to_string(),
        ]
    );
}

#[test]
fn defaults_without_a_config_file_allow_update_checks() {
    let rig = Rig::new("defaults");
    rig.answer(&defaults(), 0);
    let app = app(rig.config(TIMEOUT));

    app.scanner.refresh();

    let state = wire(&app.preferences.state());
    assert_eq!(state["config"], parsed(&defaults()));
    assert_eq!(state["outcome"], json!({"kind": "ok"}));
    assert!(app.preferences.update_check());
}

#[test]
fn the_config_path_is_the_one_the_core_resolved() {
    let rig = Rig::new("path");
    rig.answer(&defaults(), 0);
    let app = app(rig.config(TIMEOUT));

    app.scanner.refresh();

    assert_eq!(
        app.preferences.config_path(),
        Some(PathBuf::from(
            r"%USERPROFILE%\AppData\Roaming\versionbar\config.toml"
        ))
    );
}

#[test]
fn a_change_between_reads_is_picked_up_and_announced() {
    let rig = Rig::new("change");
    rig.answer(&defaults(), 0);
    let app = app(rig.config(TIMEOUT));
    app.scanner.refresh();
    assert!(app.preferences.update_check());

    rig.answer(&update_off(), 0);
    app.scanner.refresh();

    assert!(!app.preferences.update_check());
    let events = app.events.lock().unwrap();
    assert_eq!(events.len(), 2);
    assert_eq!(events[0]["config"], parsed(&defaults()));
    assert_eq!(events[1]["config"], parsed(&update_off()));
    assert_eq!(events[1], wire(&app.preferences.state()));
}

#[test]
fn an_invalid_config_keeps_its_problems_and_path_and_never_enables_updates() {
    let rig = Rig::new("invalid");
    rig.answer(&invalid(), 3);
    let app = app(rig.config(TIMEOUT));

    app.scanner.refresh();

    let state = wire(&app.preferences.state());
    // The full answer, problems included, so the popup can say what to fix.
    assert_eq!(state["config"], parsed(&invalid()));
    assert_eq!(state["outcome"], json!({"kind": "ok"}));
    assert!(!app.preferences.update_check());
    let expected = parsed(&invalid())["config_path"]
        .as_str()
        .unwrap()
        .to_owned();
    assert_eq!(app.preferences.config_path(), Some(PathBuf::from(expected)));
}

#[test]
fn an_invalid_config_keeps_the_last_known_update_setting() {
    let rig = Rig::new("invalid-after-off");
    rig.answer(&update_off(), 0);
    let app = app(rig.config(TIMEOUT));
    app.scanner.refresh();

    rig.answer(&invalid(), 3);
    app.scanner.refresh();
    assert!(!app.preferences.update_check());

    let rig = Rig::new("invalid-after-on");
    rig.answer(&defaults(), 0);
    let app = self::app(rig.config(TIMEOUT));
    app.scanner.refresh();

    rig.answer(&invalid(), 3);
    app.scanner.refresh();
    assert!(app.preferences.update_check());
}

#[test]
fn without_uv_the_outcome_says_so_and_updates_stay_off() {
    let rig = Rig::new("no-uv");
    rig.remove_uv();
    let app = app(rig.config(TIMEOUT));

    app.scanner.refresh();

    assert_eq!(
        wire(&app.preferences.state()),
        json!({"config": null, "outcome": {"kind": "uv_missing"}})
    );
    assert!(!app.preferences.update_check());
    assert!(rig.commands().is_empty());
}

/// Reads defaults (updates on), then makes the next query fail via `break_it`, and returns
/// the app after that failed read.
fn after_defaults_then(name: &str, timeout: Duration, break_it: impl FnOnce(&Rig)) -> App {
    let rig = Rig::new(name);
    rig.answer(&defaults(), 0);
    let app = app(rig.config(timeout));
    app.scanner.refresh();
    break_it(&rig);
    app.scanner.refresh();
    app
}

fn assert_failed_keeping_last(app: &App, reason: &str) {
    let state = wire(&app.preferences.state());
    assert_eq!(state["outcome"]["kind"], json!("failed"), "{state}");
    assert_eq!(state["outcome"]["reason"], json!(reason), "{state}");
    assert_eq!(state["config"], parsed(&defaults()));
    assert!(app.preferences.update_check());
    assert!(app.preferences.config_path().is_some());
}

#[test]
fn a_failing_query_keeps_the_last_answer() {
    let app = after_defaults_then("exit", TIMEOUT, |rig| rig.answer("", 2));
    assert_failed_keeping_last(&app, "exit");
}

#[test]
fn malformed_output_keeps_the_last_answer() {
    let app = after_defaults_then("malformed", TIMEOUT, |rig| {
        rig.answer("Traceback (most recent call last):", 0)
    });
    assert_failed_keeping_last(&app, "malformed");
}

#[test]
fn an_answer_without_an_update_flag_is_malformed() {
    let mut answer = parsed(&defaults());
    answer["preferences"] = Value::Null;
    let app = after_defaults_then("no-flag", TIMEOUT, |rig| rig.answer(&answer.to_string(), 0));
    assert_failed_keeping_last(&app, "malformed");
}

#[test]
fn a_hanging_query_times_out_and_keeps_the_last_answer() {
    let app = after_defaults_then("hang", Duration::from_millis(500), |rig| rig.hang());
    assert_failed_keeping_last(&app, "timeout");
}

#[test]
fn uv_disappearing_keeps_the_last_answer() {
    let app = after_defaults_then("uv-gone", TIMEOUT, |rig| rig.remove_uv());
    let state = wire(&app.preferences.state());
    assert_eq!(state["outcome"], json!({"kind": "uv_missing"}));
    assert_eq!(state["config"], parsed(&defaults()));
    assert!(app.preferences.update_check());
}

#[test]
fn a_query_failure_with_nothing_known_leaves_updates_off() {
    let rig = Rig::new("first-fails");
    rig.answer("", 1);
    let app = app(rig.config(TIMEOUT));

    app.scanner.refresh();

    let state = wire(&app.preferences.state());
    assert_eq!(state["outcome"]["kind"], json!("failed"));
    assert_eq!(state["config"], Value::Null);
    assert!(!app.preferences.update_check());
    assert_eq!(app.preferences.config_path(), None);
}
