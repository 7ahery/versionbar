//! The scan and state commands, driven through `Scanner` with a fake `uv` script in place of
//! the real one (AGENTS.md "Testing": the Rust seam). Each fake records the arguments and the
//! environment directory it was given and prints whatever the case needs.

use std::{
    ffi::OsString,
    fs,
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicUsize, Ordering},
    },
    thread,
    time::{Duration, Instant},
};

use serde_json::{Value, json};
use tray_shell::scan::{ScanConfig, Scanner, ShellState, find_uv, refresh_every};

/// Real `versionbar list --json` output from a Windows machine (profile path redacted).
fn real_scan() -> String {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../src/test/fixtures/list-windows.json");
    fs::read_to_string(&path).unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()))
}

/// A fresh, empty directory per test so parallel tests never share fakes or records.
fn scratch(name: &str) -> PathBuf {
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    let dir = std::env::temp_dir().join(format!(
        "tray-shell-test-{}-{}-{name}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::SeqCst)
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    dir
}

/// What the fake `uv` does after recording how it was called.
enum Fake<'a> {
    /// Print this file's contents to stdout and exit 0.
    Print(&'a str),
    /// Print to stderr and exit with this code.
    Fail(&'a str, i32),
    /// Never finish on its own.
    Hang,
}

struct Rig {
    dir: PathBuf,
    uv: PathBuf,
}

impl Rig {
    fn new(name: &str, fake: Fake) -> Self {
        let dir = scratch(name);
        let uv = write_fake(&dir, fake);
        Rig { dir, uv }
    }

    fn config(&self, timeout: Duration) -> ScanConfig {
        let uv = self.uv.clone();
        ScanConfig {
            find_uv: Box::new(move || Some(uv.clone())),
            project: self.dir.join("core"),
            environment: self.dir.join("core-env"),
            state_file: self.dir.join("scan-state.json"),
            timeout,
            first_run_timeout: timeout,
        }
    }

    /// The arguments the fake received, one per line.
    fn recorded_args(&self) -> Vec<String> {
        fs::read_to_string(self.dir.join("args.txt"))
            .unwrap_or_default()
            .lines()
            .map(|line| line.trim().to_owned())
            .filter(|line| !line.is_empty())
            .collect()
    }

    /// `UV_PROJECT_ENVIRONMENT` and `PYTHONPYCACHEPREFIX` as the fake saw them.
    fn recorded_environment(&self) -> Vec<String> {
        fs::read_to_string(self.dir.join("env.txt"))
            .unwrap_or_default()
            .lines()
            .map(|line| line.trim().to_owned())
            .collect()
    }

    fn calls(&self) -> usize {
        fs::read_to_string(self.dir.join("calls.txt"))
            .unwrap_or_default()
            .lines()
            .count()
    }
}

#[cfg(windows)]
fn write_fake(dir: &Path, fake: Fake) -> PathBuf {
    let record = format!(
        "@echo off\r\n\
         echo call>>\"{d}\\calls.txt\"\r\n\
         for %%a in (%*) do echo %%~a>>\"{d}\\args.txt\"\r\n\
         echo %UV_PROJECT_ENVIRONMENT%>\"{d}\\env.txt\"\r\n\
         echo %PYTHONPYCACHEPREFIX%>>\"{d}\\env.txt\"\r\n",
        d = dir.display()
    );
    let action = match fake {
        Fake::Print(file) => format!("type \"{}\"\r\nexit /b 0\r\n", dir.join(file).display()),
        Fake::Fail(message, code) => format!("echo {message} 1>&2\r\nexit /b {code}\r\n"),
        Fake::Hang => "ping -n 60 127.0.0.1 >nul\r\n".to_owned(),
    };
    let path = dir.join("uv.cmd");
    fs::write(&path, record + &action).unwrap();
    path
}

#[cfg(not(windows))]
fn write_fake(dir: &Path, fake: Fake) -> PathBuf {
    use std::os::unix::fs::PermissionsExt;
    let record = format!(
        "#!/bin/sh\n\
         echo call >> '{d}/calls.txt'\n\
         for a in \"$@\"; do echo \"$a\" >> '{d}/args.txt'; done\n\
         echo \"$UV_PROJECT_ENVIRONMENT\" > '{d}/env.txt'\n\
         echo \"$PYTHONPYCACHEPREFIX\" >> '{d}/env.txt'\n",
        d = dir.display()
    );
    let action = match fake {
        Fake::Print(file) => format!("cat '{}'\nexit 0\n", dir.join(file).display()),
        Fake::Fail(message, code) => format!("echo '{message}' >&2\nexit {code}\n"),
        Fake::Hang => "sleep 60\n".to_owned(),
    };
    let path = dir.join("uv");
    fs::write(&path, record + &action).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    path
}

/// A rig whose fake prints `output` verbatim.
fn printing(name: &str, output: &str) -> Rig {
    let rig = Rig::new(name, Fake::Print("out.json"));
    fs::write(rig.dir.join("out.json"), output).unwrap();
    rig
}

const TIMEOUT: Duration = Duration::from_secs(30);

fn scanner(config: ScanConfig) -> Scanner {
    Scanner::new(config, Box::new(|_: &ShellState| {}))
}

/// The state exactly as the popup receives it over IPC.
fn wire(state: &ShellState) -> Value {
    serde_json::to_value(state).unwrap()
}

fn parsed(text: &str) -> Value {
    serde_json::from_str(text).unwrap()
}

#[test]
fn before_any_scan_the_state_is_empty() {
    let rig = printing("empty", &real_scan());
    let scanner = scanner(rig.config(TIMEOUT));

    assert_eq!(
        wire(&scanner.state()),
        json!({"scanning": false, "setting_up": false, "current": null, "previous": null, "outcome": null})
    );
}

#[test]
fn a_successful_scan_becomes_the_current_result_unchanged() {
    let rig = printing("success", &real_scan());
    let scanner = scanner(rig.config(TIMEOUT));

    scanner.refresh();

    let state = wire(&scanner.state());
    assert_eq!(state["outcome"], json!({"kind": "ok"}));
    assert_eq!(state["scanning"], json!(false));
    assert_eq!(state["current"], parsed(&real_scan()));
    assert_eq!(state["previous"], Value::Null);
}

#[test]
fn the_core_runs_with_fixed_arguments_and_the_environment_in_app_data() {
    let rig = printing("arguments", &real_scan());
    let scanner = scanner(rig.config(TIMEOUT));

    scanner.refresh();

    let project = rig.dir.join("core").display().to_string();
    assert_eq!(
        rig.recorded_args(),
        [
            "run",
            "--frozen",
            "--no-dev",
            "--managed-python",
            "--project",
            project.as_str(),
            "--",
            "versionbar",
            "list",
            "--json",
        ]
    );
    // Both the environment and Python's bytecode cache stay out of the install folder.
    assert_eq!(
        rig.recorded_environment(),
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
fn a_second_scan_keeps_the_first_as_previous() {
    let rig = printing("rotation", &real_scan());
    let scanner = scanner(rig.config(TIMEOUT));
    scanner.refresh();

    let mut newer = parsed(&real_scan());
    newer["scanned_at"] = json!("2026-10-24T10:00:00Z");
    fs::write(rig.dir.join("out.json"), newer.to_string()).unwrap();
    scanner.refresh();

    let state = wire(&scanner.state());
    assert_eq!(state["current"], newer);
    assert_eq!(state["previous"], parsed(&real_scan()));
}

#[test]
fn unknown_fields_and_tool_contents_pass_through_untouched() {
    // Rust must not drop or reshape anything it does not understand (ADR-0006).
    let mut scan = parsed(&real_scan());
    scan["added_later"] = json!({"nested": [1, 2, 3]});
    scan["tools"][0]["status"] = json!("some-future-status");
    let rig = printing("opaque", &scan.to_string());
    let scanner = scanner(rig.config(TIMEOUT));

    scanner.refresh();

    assert_eq!(wire(&scanner.state())["current"], scan);
}

/// Runs one successful scan, then one that fails, and returns the final state.
fn after_success_then(name: &str, fake: Fake, timeout: Duration) -> (Value, Duration) {
    let good = printing(&format!("{name}-good"), &real_scan());
    let bad = Rig::new(name, fake);
    let use_bad = Arc::new(Mutex::new(false));
    let (good_uv, bad_uv) = (good.uv.clone(), bad.uv.clone());
    let switch = use_bad.clone();
    let config = ScanConfig {
        find_uv: Box::new(move || {
            Some(if *switch.lock().unwrap() {
                bad_uv.clone()
            } else {
                good_uv.clone()
            })
        }),
        project: bad.dir.join("core"),
        environment: bad.dir.join("core-env"),
        state_file: bad.dir.join("scan-state.json"),
        timeout,
        first_run_timeout: timeout,
    };
    let scanner = scanner(config);
    scanner.refresh();
    *use_bad.lock().unwrap() = true;

    let started = Instant::now();
    scanner.refresh();
    (wire(&scanner.state()), started.elapsed())
}

#[test]
fn a_nonzero_exit_is_a_failure_that_carries_stderr_and_keeps_the_last_result() {
    let (state, _) = after_success_then(
        "nonzero",
        Fake::Fail("error: no interpreter found", 2),
        TIMEOUT,
    );

    assert_eq!(state["outcome"]["kind"], json!("failed"));
    assert_eq!(state["outcome"]["reason"], json!("exit"));
    assert_eq!(
        state["outcome"]["stderr"],
        json!("error: no interpreter found")
    );
    assert!(
        state["outcome"]["message"]
            .as_str()
            .unwrap()
            .contains("code 2"),
        "{state}"
    );
    assert_eq!(state["current"], parsed(&real_scan()));
    assert_eq!(state["scanning"], json!(false));
}

#[test]
fn a_scan_that_runs_too_long_is_stopped_and_reported_as_a_timeout() {
    let (state, elapsed) = after_success_then("timeout", Fake::Hang, Duration::from_millis(500));

    assert_eq!(state["outcome"]["kind"], json!("failed"));
    assert_eq!(state["outcome"]["reason"], json!("timeout"));
    assert!(elapsed < Duration::from_secs(10), "took {elapsed:?}");
    assert_eq!(state["current"], parsed(&real_scan()));
}

#[test]
fn output_that_is_not_json_is_a_failure() {
    let rig = printing("malformed", "Traceback (most recent call last):\n  oops\n");
    let scanner = scanner(rig.config(TIMEOUT));

    scanner.refresh();

    let state = wire(&scanner.state());
    assert_eq!(state["outcome"]["kind"], json!("failed"));
    assert_eq!(state["outcome"]["reason"], json!("malformed"));
    assert_eq!(state["current"], Value::Null);
}

#[test]
fn json_that_is_not_an_object_is_a_failure() {
    let rig = printing("array", "[1, 2]");
    let scanner = scanner(rig.config(TIMEOUT));

    scanner.refresh();

    assert_eq!(
        wire(&scanner.state())["outcome"]["reason"],
        json!("malformed")
    );
}

#[test]
fn an_unsupported_schema_version_is_a_failure() {
    let mut scan = parsed(&real_scan());
    scan["schema_version"] = json!(2);
    let rig = printing("mismatch", &scan.to_string());
    let scanner = scanner(rig.config(TIMEOUT));

    scanner.refresh();

    let state = wire(&scanner.state());
    assert_eq!(state["outcome"]["kind"], json!("failed"));
    assert_eq!(state["outcome"]["reason"], json!("incompatible"));
    assert!(
        state["outcome"]["message"].as_str().unwrap().contains('2'),
        "{state}"
    );
    assert_eq!(state["current"], Value::Null);
}

#[test]
fn a_result_without_a_schema_version_is_a_failure() {
    let rig = printing("unversioned", r#"{"tools": []}"#);
    let scanner = scanner(rig.config(TIMEOUT));

    scanner.refresh();

    assert_eq!(
        wire(&scanner.state())["outcome"]["reason"],
        json!("incompatible")
    );
}

#[test]
fn without_uv_the_outcome_is_uv_missing_and_nothing_runs() {
    let rig = printing("no-uv", &real_scan());
    let mut config = rig.config(TIMEOUT);
    config.find_uv = Box::new(|| None);
    let announced: Arc<Mutex<Vec<Value>>> = Arc::default();
    let sink = announced.clone();
    // The environment folder does not exist: a first run, but with no uv there is nothing to
    // set up, so the popup must not be told to show the setup screen.
    let scanner = Scanner::new(
        config,
        Box::new(move |state: &ShellState| sink.lock().unwrap().push(wire(state))),
    );

    scanner.refresh();

    let state = wire(&scanner.state());
    assert_eq!(state["outcome"], json!({"kind": "uv_missing"}));
    assert_eq!(rig.calls(), 0);
    assert!(
        announced
            .lock()
            .unwrap()
            .iter()
            .all(|state| state["setting_up"] == json!(false))
    );
}

#[test]
fn a_uv_that_cannot_be_started_is_a_launch_failure() {
    let rig = printing("launch", &real_scan());
    let mut config = rig.config(TIMEOUT);
    let gone = rig
        .dir
        .join("deleted")
        .join(if cfg!(windows) { "uv.exe" } else { "uv" });
    config.find_uv = Box::new(move || Some(gone.clone()));
    let scanner = scanner(config);

    scanner.refresh();

    let state = wire(&scanner.state());
    assert_eq!(state["outcome"]["kind"], json!("failed"));
    assert_eq!(state["outcome"]["reason"], json!("launch"));
}

/// Starts a refresh on another thread and waits until its scan is running.
fn refresh_in_background(scanner: &Arc<Scanner>) -> thread::JoinHandle<bool> {
    let handle = {
        let scanner = scanner.clone();
        thread::spawn(move || scanner.refresh())
    };
    let deadline = Instant::now() + Duration::from_secs(5);
    while !scanner.state().scanning() {
        assert!(Instant::now() < deadline, "scan never started");
        thread::sleep(Duration::from_millis(10));
    }
    handle
}

#[test]
fn every_change_is_announced_and_a_single_refresh_runs_one_scan() {
    let rig = Rig::new("announce", Fake::Hang);
    let announced: Arc<Mutex<Vec<Value>>> = Arc::default();
    let sink = announced.clone();
    let scanner = Scanner::new(
        rig.config(Duration::from_millis(300)),
        Box::new(move |state: &ShellState| sink.lock().unwrap().push(wire(state))),
    );

    assert!(scanner.refresh());

    assert_eq!(rig.calls(), 1);
    let announced = announced.lock().unwrap();
    assert_eq!(announced.len(), 2, "{announced:?}");
    assert_eq!(announced[0]["scanning"], json!(true));
    assert_eq!(announced[1]["scanning"], json!(false));
    assert_eq!(announced[1]["outcome"]["reason"], json!("timeout"));
}

#[test]
fn refreshes_during_a_scan_never_overlap_and_are_answered_by_one_more_scan() {
    // A request made while a scan runs may follow a config edit the running scan missed
    // (spec story 58), so it gets a scan of its own; any number of them share that one.
    let rig = Rig::new("overlap", Fake::Hang);
    let announced: Arc<Mutex<Vec<Value>>> = Arc::default();
    let sink = announced.clone();
    let scanner = Arc::new(Scanner::new(
        rig.config(Duration::from_millis(500)),
        Box::new(move |state: &ShellState| sink.lock().unwrap().push(wire(state))),
    ));

    let first = refresh_in_background(&scanner);
    for _ in 0..3 {
        assert!(
            !scanner.refresh(),
            "the running scan's caller does the extra scan, not this one"
        );
    }
    assert!(first.join().unwrap());

    assert_eq!(rig.calls(), 2);
    let announced = announced.lock().unwrap();
    let scanning: Vec<_> = announced
        .iter()
        .map(|state| state["scanning"].clone())
        .collect();
    // The first result is announced with the extra scan already under way, so the popup never
    // sees an idle moment between the two.
    assert_eq!(
        scanning,
        [json!(true), json!(true), json!(false)],
        "{announced:?}"
    );
    assert_eq!(announced[1]["outcome"]["reason"], json!("timeout"));
}

#[test]
fn the_background_schedule_scans_at_once_then_on_every_interval_until_the_scanner_goes() {
    let rig = printing("interval", &real_scan());
    let scanner = Arc::new(scanner(rig.config(TIMEOUT)));
    let finished = Arc::new(AtomicUsize::new(0));
    let count = finished.clone();

    let schedule = refresh_every(&scanner, Duration::from_millis(400), move |scanner| {
        assert!(!scanner.state().scanning());
        count.fetch_add(1, Ordering::SeqCst);
    });

    let deadline = Instant::now() + Duration::from_secs(20);
    while finished.load(Ordering::SeqCst) < 3 {
        assert!(Instant::now() < deadline, "only {} scans", rig.calls());
        thread::sleep(Duration::from_millis(20));
    }
    assert!(rig.calls() >= 3);
    assert_eq!(wire(&scanner.state())["outcome"], json!({"kind": "ok"}));

    drop(scanner);
    schedule.join().unwrap();
    let after_stop = rig.calls();
    thread::sleep(Duration::from_millis(900));
    assert_eq!(rig.calls(), after_stop);
}

#[test]
fn the_first_scheduled_scan_does_not_wait_for_the_interval() {
    let rig = printing("startup", &real_scan());
    let scanner = Arc::new(scanner(rig.config(TIMEOUT)));

    let _schedule = refresh_every(&scanner, Duration::from_secs(3600), |_| {});

    let deadline = Instant::now() + Duration::from_secs(20);
    while wire(&scanner.state())["outcome"].is_null() {
        assert!(Instant::now() < deadline, "no startup scan");
        thread::sleep(Duration::from_millis(20));
    }
    assert_eq!(rig.calls(), 1);
}

// First run versus later runs: the environment folder decides how long uv may take, because
// the first run downloads Python and packages (spec "Scan command").

/// Whichever timeout the scanner picks decides how quickly the hanging fake is stopped.
fn time_a_hanging_scan(name: &str, environment_exists: bool, normal: u64, first: u64) -> Duration {
    let rig = Rig::new(name, Fake::Hang);
    if environment_exists {
        fs::create_dir_all(rig.dir.join("core-env")).unwrap();
    }
    let mut config = rig.config(Duration::from_millis(normal));
    config.first_run_timeout = Duration::from_millis(first);
    let scanner = scanner(config);
    let started = Instant::now();
    scanner.refresh();
    let elapsed = started.elapsed();
    assert_eq!(
        wire(&scanner.state())["outcome"]["reason"],
        json!("timeout")
    );
    elapsed
}

#[test]
fn without_an_environment_folder_the_first_run_timeout_applies() {
    let elapsed = time_a_hanging_scan("first-run-long", false, 300, 1_500);
    assert!(elapsed >= Duration::from_millis(1_500), "{elapsed:?}");
}

#[test]
fn with_an_environment_folder_the_normal_timeout_applies() {
    let elapsed = time_a_hanging_scan("later-run-short", true, 300, 20_000);
    assert!(elapsed < Duration::from_secs(10), "{elapsed:?}");
}

#[test]
fn a_first_run_that_timed_out_keeps_the_first_run_rules_until_a_scan_succeeds() {
    let hang = Rig::new("unsettled-hang", Fake::Hang);
    let good = printing("unsettled-good", &real_scan());
    let (hang_uv, good_uv) = (hang.uv.clone(), good.uv.clone());
    let chosen = Arc::new(Mutex::new(hang_uv.clone()));
    let lookup = chosen.clone();
    let mut config = hang.config(Duration::from_millis(300));
    config.first_run_timeout = Duration::from_millis(1_500);
    config.find_uv = Box::new(move || Some(lookup.lock().unwrap().clone()));
    let announced: Arc<Mutex<Vec<Value>>> = Arc::default();
    let sink = announced.clone();
    let scanner = Scanner::new(
        config,
        Box::new(move |state: &ShellState| sink.lock().unwrap().push(wire(state))),
    );
    let timed = || {
        let started = Instant::now();
        scanner.refresh();
        started.elapsed()
    };
    let last_started_setting_up = || {
        announced
            .lock()
            .unwrap()
            .iter()
            .rev()
            .find(|state| state["scanning"] == json!(true))
            .map(|state| state["setting_up"] == json!(true))
            .unwrap()
    };

    assert!(timed() >= Duration::from_millis(1_500));
    // uv got as far as creating the folder before the timeout.
    fs::create_dir_all(hang.dir.join("core-env")).unwrap();

    assert!(
        timed() >= Duration::from_millis(1_500),
        "retry is still a first run"
    );
    assert!(last_started_setting_up());

    *chosen.lock().unwrap() = good_uv;
    scanner.refresh();
    assert_eq!(wire(&scanner.state())["outcome"], json!({"kind": "ok"}));
    assert!(last_started_setting_up());

    *chosen.lock().unwrap() = hang_uv;
    assert!(
        timed() < Duration::from_millis(1_200),
        "now an ordinary scan"
    );
    assert!(!last_started_setting_up());
}

#[test]
fn the_state_says_setting_up_only_for_a_first_run_and_clears_afterwards() {
    for (environment_exists, expected) in [(false, true), (true, false)] {
        let rig = printing(&format!("setup-{environment_exists}"), &real_scan());
        if environment_exists {
            fs::create_dir_all(rig.dir.join("core-env")).unwrap();
        }
        let announced: Arc<Mutex<Vec<Value>>> = Arc::default();
        let sink = announced.clone();
        let scanner = Scanner::new(
            rig.config(TIMEOUT),
            Box::new(move |state: &ShellState| sink.lock().unwrap().push(wire(state))),
        );

        scanner.refresh();

        let announced = announced.lock().unwrap();
        assert_eq!(announced[0]["scanning"], json!(true));
        assert_eq!(announced[0]["setting_up"], json!(expected), "{announced:?}");
        assert_eq!(announced[1]["setting_up"], json!(false));
    }
}

/// Whether each of `scans` consecutive scans over an existing environment started as a first
/// run, for a scanner that marks the environment with `version`. `marker` is what an earlier
/// app version left in the marker file (None: no file).
fn first_runs_after_marker(
    name: &str,
    marker: Option<&str>,
    version: &str,
    scans: usize,
) -> Vec<bool> {
    let rig = printing(name, &real_scan());
    fs::create_dir_all(rig.dir.join("core-env")).unwrap();
    let marker_file = rig.dir.join("core-env-version.txt");
    if let Some(marker) = marker {
        fs::write(&marker_file, marker).unwrap();
    }
    let announced: Arc<Mutex<Vec<Value>>> = Arc::default();
    let sink = announced.clone();
    let scanner = Scanner::new(
        rig.config(TIMEOUT),
        Box::new(move |state: &ShellState| sink.lock().unwrap().push(wire(state))),
    )
    .with_version_marker(marker_file, version.to_owned());
    for _ in 0..scans {
        scanner.refresh();
    }
    let announced = announced.lock().unwrap();
    announced
        .iter()
        .filter(|state| state["scanning"] == json!(true))
        .map(|state| state["setting_up"] == json!(true))
        .collect()
}

#[test]
fn the_first_scan_after_the_app_version_changes_is_a_first_run() {
    assert_eq!(
        first_runs_after_marker("marker-older", Some("0.1.0"), "0.2.0", 2),
        [true, false],
        "an update: one first run, then ordinary scans"
    );
    assert_eq!(
        first_runs_after_marker("marker-same", Some("0.2.0"), "0.2.0", 1),
        [false]
    );
    assert_eq!(
        first_runs_after_marker("marker-missing", None, "0.2.0", 2),
        [true, false],
        "an environment from a build before the marker existed"
    );
}

#[test]
fn a_version_change_gets_the_first_run_timeout() {
    let rig = Rig::new("marker-timeout", Fake::Hang);
    fs::create_dir_all(rig.dir.join("core-env")).unwrap();
    fs::write(rig.dir.join("core-env-version.txt"), "0.1.0").unwrap();
    let mut config = rig.config(Duration::from_millis(300));
    config.first_run_timeout = Duration::from_millis(1_500);
    let scanner =
        scanner(config).with_version_marker(rig.dir.join("core-env-version.txt"), "0.2.0".into());

    let started = Instant::now();
    scanner.refresh();

    assert!(started.elapsed() >= Duration::from_millis(1_500));
    // Only a successful scan settles the new version.
    assert_eq!(
        fs::read_to_string(rig.dir.join("core-env-version.txt")).unwrap(),
        "0.1.0"
    );
}

#[test]
fn a_failed_first_run_reports_stderr_and_a_retry_with_uv_working_succeeds() {
    let bad = Rig::new("retry-bad", Fake::Fail("error: network unreachable", 2));
    let good = printing("retry-good", &real_scan());
    let good_uv = good.uv.clone();
    let chosen = Arc::new(Mutex::new(bad.uv.clone()));
    let lookup = chosen.clone();
    let mut config = bad.config(TIMEOUT);
    config.find_uv = Box::new(move || Some(lookup.lock().unwrap().clone()));
    let scanner = scanner(config);

    scanner.refresh();
    let failed = wire(&scanner.state());
    assert_eq!(failed["outcome"]["kind"], json!("failed"));
    assert_eq!(
        failed["outcome"]["stderr"],
        json!("error: network unreachable")
    );
    assert_eq!(failed["current"], Value::Null);

    *chosen.lock().unwrap() = good_uv;
    scanner.refresh();
    let recovered = wire(&scanner.state());
    assert_eq!(recovered["outcome"], json!({"kind": "ok"}));
    assert_eq!(recovered["current"], parsed(&real_scan()));
}

#[test]
fn uv_missing_is_reported_until_uv_appears() {
    let rig = printing("missing-then-found", &real_scan());
    let uv = rig.uv.clone();
    let present = Arc::new(Mutex::new(false));
    let lookup = present.clone();
    let mut config = rig.config(TIMEOUT);
    config.find_uv = Box::new(move || lookup.lock().unwrap().then(|| uv.clone()));
    let scanner = scanner(config);

    scanner.refresh();
    assert!(scanner.state().uv_missing());
    assert_eq!(rig.calls(), 0);

    *present.lock().unwrap() = true;
    scanner.refresh();
    assert!(!scanner.state().uv_missing());
}

// Saved state: the last two successful results survive a restart (spec stories 37 and 53).

/// The scan fixture with a different `scanned_at`, so two results can be told apart.
fn scan_at(scanned_at: &str) -> Value {
    let mut scan = parsed(&real_scan());
    scan["scanned_at"] = json!(scanned_at);
    scan
}

#[test]
fn a_restarted_shell_starts_from_the_saved_results_without_scanning() {
    let rig = printing("restore", &real_scan());
    let first = scanner(rig.config(TIMEOUT));
    first.refresh();
    let newer = scan_at("2026-10-24T10:00:00Z");
    fs::write(rig.dir.join("out.json"), newer.to_string()).unwrap();
    first.refresh();
    drop(first);

    let restarted = scanner(rig.config(TIMEOUT));

    // Nothing has run in this session yet, so there is no outcome to report.
    assert_eq!(
        wire(&restarted.state()),
        json!({
            "scanning": false,
            "setting_up": false,
            "current": newer,
            "previous": parsed(&real_scan()),
            "outcome": null,
        })
    );
    assert_eq!(rig.calls(), 2);
}

/// What a fresh scanner over `rig` starts with, after `saved` was left in its state file.
fn restored_from(rig: &Rig, saved: &str) -> Value {
    fs::write(rig.dir.join("scan-state.json"), saved).unwrap();
    wire(&scanner(rig.config(TIMEOUT)).state())
}

/// A state file as this build writes it, holding `current` and `previous`.
fn saved_pair(current: &Value, previous: &Value) -> String {
    json!({"format": 1, "current": current, "previous": previous}).to_string()
}

#[test]
fn a_damaged_or_foreign_state_file_is_ignored_and_the_shell_starts_empty() {
    let rig = printing("discard", &real_scan());
    let good = parsed(&real_scan());
    let mut future = good.clone();
    future["schema_version"] = json!(2);
    let cases = [
        ("truncated mid-write", real_scan()[..200].to_owned()),
        ("not JSON at all", "\u{0}\u{0}\u{0}".to_owned()),
        ("an empty file", String::new()),
        ("a bare scan, not this file's layout", real_scan()),
        (
            "an unknown layout version",
            json!({"format": 2, "current": good, "previous": null}).to_string(),
        ),
        (
            "a current scan from a newer core",
            saved_pair(&future, &Value::Null),
        ),
        (
            "a previous scan from a newer core",
            saved_pair(&good, &future),
        ),
        (
            "a current that is not an object",
            saved_pair(&json!([1]), &Value::Null),
        ),
    ];
    for (case, saved) in cases {
        let state = restored_from(&rig, &saved);
        assert_eq!(state["current"], Value::Null, "{case}");
        assert_eq!(state["previous"], Value::Null, "{case}");
        assert_eq!(state["outcome"], Value::Null, "{case}");
    }
}

#[test]
fn after_a_damaged_state_file_the_next_scan_saves_a_good_one() {
    let rig = printing("discard-then-save", &real_scan());
    fs::write(rig.dir.join("scan-state.json"), "{\"format\": 1, \"curr").unwrap();
    scanner(rig.config(TIMEOUT)).refresh();

    let restarted = wire(&scanner(rig.config(TIMEOUT)).state());

    assert_eq!(restarted["current"], parsed(&real_scan()));
    assert_eq!(restarted["previous"], Value::Null);
}

#[test]
fn a_leftover_temporary_file_from_an_interrupted_save_changes_nothing() {
    let rig = printing("interrupted", &real_scan());
    scanner(rig.config(TIMEOUT)).refresh();
    // A save writes here first and then renames it into place; a crash in between leaves it.
    fs::write(rig.dir.join("scan-state.json.tmp"), &real_scan()[..100]).unwrap();

    let restarted = scanner(rig.config(TIMEOUT));
    assert_eq!(wire(&restarted.state())["current"], parsed(&real_scan()));

    let newer = scan_at("2026-10-24T10:00:00Z");
    fs::write(rig.dir.join("out.json"), newer.to_string()).unwrap();
    restarted.refresh();
    let again = wire(&scanner(rig.config(TIMEOUT)).state());
    assert_eq!(again["current"], newer);
    assert_eq!(again["previous"], parsed(&real_scan()));
}

#[test]
fn a_failed_scan_leaves_the_saved_pair_alone() {
    let rig = printing("failed-keeps-saved", &real_scan());
    let first = scanner(rig.config(TIMEOUT));
    first.refresh();
    fs::write(rig.dir.join("out.json"), "not a scan").unwrap();
    first.refresh();
    assert_eq!(
        wire(&first.state())["outcome"]["reason"],
        json!("malformed")
    );

    let restarted = wire(&scanner(rig.config(TIMEOUT)).state());

    assert_eq!(restarted["current"], parsed(&real_scan()));
}

#[test]
fn results_that_cannot_be_saved_are_still_shown() {
    let rig = printing("unwritable", &real_scan());
    let mut config = rig.config(TIMEOUT);
    // A file where the state file's folder should be: nothing can be written below it.
    fs::write(rig.dir.join("blocked"), "").unwrap();
    config.state_file = rig.dir.join("blocked").join("scan-state.json");
    let scanner = scanner(config);

    scanner.refresh();

    let state = wire(&scanner.state());
    assert_eq!(state["outcome"], json!({"kind": "ok"}));
    assert_eq!(state["current"], parsed(&real_scan()));
}

#[test]
fn the_state_file_is_created_with_its_folder() {
    let rig = printing("new-folder", &real_scan());
    let mut config = rig.config(TIMEOUT);
    config.state_file = rig.dir.join("app-data").join("scan-state.json");
    scanner(config).refresh();

    let mut config = rig.config(TIMEOUT);
    config.state_file = rig.dir.join("app-data").join("scan-state.json");
    assert_eq!(
        wire(&scanner(config).state())["current"],
        parsed(&real_scan())
    );
}

#[test]
fn restored_results_do_not_shorten_a_first_run() {
    // Saved results say nothing about the environment: with core-env gone, the scan is still
    // a first run with the long timeout and the setup flag, alongside the restored data.
    let rig = Rig::new("restored-first-run", Fake::Hang);
    fs::write(
        rig.dir.join("scan-state.json"),
        saved_pair(&parsed(&real_scan()), &Value::Null),
    )
    .unwrap();
    let mut config = rig.config(Duration::from_millis(300));
    config.first_run_timeout = Duration::from_millis(1_500);
    let announced: Arc<Mutex<Vec<Value>>> = Arc::default();
    let sink = announced.clone();
    let scanner = Scanner::new(
        config,
        Box::new(move |state: &ShellState| sink.lock().unwrap().push(wire(state))),
    );

    let started = Instant::now();
    scanner.refresh();

    assert!(started.elapsed() >= Duration::from_millis(1_500));
    let announced = announced.lock().unwrap();
    assert_eq!(announced[0]["setting_up"], json!(true));
    assert_eq!(announced[0]["current"], parsed(&real_scan()));
    assert_eq!(announced[1]["outcome"]["reason"], json!("timeout"));
    assert_eq!(announced[1]["current"], parsed(&real_scan()));
}

// uv lookup: PATH, then UV_INSTALL_DIR, then the default user-local bin (~/.local/bin).

fn exe(name: &str) -> String {
    if cfg!(windows) {
        format!("{name}.exe")
    } else {
        name.to_owned()
    }
}

fn place_uv(dir: &Path) -> PathBuf {
    fs::create_dir_all(dir).unwrap();
    let path = dir.join(exe("uv"));
    fs::write(&path, "").unwrap();
    path
}

fn home_var() -> &'static str {
    if cfg!(windows) { "USERPROFILE" } else { "HOME" }
}

/// Looks uv up with only the given variables set.
fn lookup(vars: &[(&str, OsString)]) -> Option<PathBuf> {
    find_uv(&|key: &str| {
        vars.iter()
            .find(|(name, _)| *name == key)
            .map(|(_, value)| value.clone())
    })
}

fn path_of(dirs: &[&Path]) -> OsString {
    std::env::join_paths(dirs).unwrap()
}

#[test]
fn uv_on_path_wins() {
    let root = scratch("lookup-path");
    let (empty, on_path, install, home) = (
        root.join("empty"),
        root.join("bin"),
        root.join("install"),
        root.join("home"),
    );
    fs::create_dir_all(&empty).unwrap();
    let expected = place_uv(&on_path);
    place_uv(&install);
    place_uv(&home.join(".local").join("bin"));

    let found = lookup(&[
        ("PATH", path_of(&[&empty, &on_path])),
        ("UV_INSTALL_DIR", install.into()),
        (home_var(), home.into()),
    ]);

    assert_eq!(found, Some(expected));
}

#[test]
fn uv_install_dir_is_used_when_uv_is_not_on_path() {
    let root = scratch("lookup-install-dir");
    let (empty, install, home) = (root.join("empty"), root.join("install"), root.join("home"));
    fs::create_dir_all(&empty).unwrap();
    let expected = place_uv(&install);
    place_uv(&home.join(".local").join("bin"));

    let found = lookup(&[
        ("PATH", path_of(&[&empty])),
        ("UV_INSTALL_DIR", install.into()),
        (home_var(), home.into()),
    ]);

    assert_eq!(found, Some(expected));
}

#[test]
fn the_default_user_local_bin_is_the_last_resort() {
    // An app started at login may not see the shell's PATH (spec story 65).
    let root = scratch("lookup-home");
    let home = root.join("home");
    let expected = place_uv(&home.join(".local").join("bin"));

    let found = lookup(&[(home_var(), home.into())]);

    assert_eq!(found, Some(expected));
}

#[test]
fn no_uv_anywhere_is_none() {
    let root = scratch("lookup-none");
    let found = lookup(&[
        ("PATH", path_of(&[&root])),
        ("UV_INSTALL_DIR", root.join("install").into()),
        (home_var(), root.join("home").into()),
    ]);

    assert_eq!(found, None);
}

#[test]
fn a_directory_named_like_uv_is_not_uv() {
    let root = scratch("lookup-dir");
    fs::create_dir_all(root.join("bin").join(exe("uv"))).unwrap();

    assert_eq!(lookup(&[("PATH", path_of(&[&root.join("bin")]))]), None);
}

/// `target` written relative to the working directory, the way a relative variable would be
/// resolved if the lookup did not reject it.
fn relative_from_cwd(target: &Path) -> PathBuf {
    let cwd = std::env::current_dir().unwrap();
    let from: Vec<_> = cwd.components().collect();
    let to: Vec<_> = target.components().collect();
    let common = from.iter().zip(&to).take_while(|(a, b)| a == b).count();
    assert!(
        common > 0,
        "{} and {} share no root",
        cwd.display(),
        target.display()
    );
    let mut relative = PathBuf::new();
    for _ in common..from.len() {
        relative.push("..");
    }
    relative.extend(&to[common..]);
    relative
}

#[test]
fn relative_or_empty_lookup_folders_are_ignored() {
    // They would depend on the app's working directory, which nobody chose; PATH entries are
    // treated the same way.
    // Under the working directory, not the temp dir: on Windows they can sit on different
    // drives, and a path cannot be written relative across drives.
    let root = std::env::current_dir()
        .unwrap()
        .join("target")
        .join(format!("lookup-relative-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let install = root.join("install");
    let home = root.join("home");
    place_uv(&install);
    place_uv(&home.join(".local").join("bin"));
    let (install, home) = (relative_from_cwd(&install), relative_from_cwd(&home));
    assert!(install.join(exe("uv")).is_file(), "{}", install.display());

    assert_eq!(
        lookup(&[
            ("UV_INSTALL_DIR", install.into()),
            (home_var(), home.into())
        ]),
        None
    );
    assert_eq!(
        lookup(&[
            ("PATH", OsString::new()),
            ("UV_INSTALL_DIR", OsString::new()),
            (home_var(), OsString::new())
        ]),
        None
    );
}
