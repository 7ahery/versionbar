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
use tray_shell::scan::{ScanConfig, Scanner, ShellState, find_uv};

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
    let scanner = scanner(config);

    scanner.refresh();

    let state = wire(&scanner.state());
    assert_eq!(state["outcome"], json!({"kind": "uv_missing"}));
    assert_eq!(rig.calls(), 0);
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

#[test]
fn every_change_is_announced_and_a_refresh_during_a_scan_is_skipped() {
    let rig = Rig::new("overlap", Fake::Hang);
    let announced: Arc<Mutex<Vec<Value>>> = Arc::default();
    let sink = announced.clone();
    let scanner = Arc::new(Scanner::new(
        rig.config(Duration::from_secs(2)),
        Box::new(move |state: &ShellState| sink.lock().unwrap().push(wire(state))),
    ));

    let first = {
        let scanner = scanner.clone();
        thread::spawn(move || scanner.refresh())
    };
    let deadline = Instant::now() + Duration::from_secs(5);
    while !scanner.state().scanning() {
        assert!(Instant::now() < deadline, "scan never started");
        thread::sleep(Duration::from_millis(10));
    }
    assert!(
        !scanner.refresh(),
        "a second scan must not start while one runs"
    );
    assert!(first.join().unwrap());

    assert_eq!(rig.calls(), 1);
    let announced = announced.lock().unwrap();
    assert_eq!(announced.len(), 2, "{announced:?}");
    assert_eq!(announced[0]["scanning"], json!(true));
    assert_eq!(announced[1]["scanning"], json!(false));
    assert_eq!(announced[1]["outcome"]["reason"], json!("timeout"));
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
    let root = scratch("lookup-relative");
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
