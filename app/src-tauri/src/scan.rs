//! Running the bundled core and holding its results (spec "Scan command", "State ownership").
//!
//! The shell runs exactly one fixed invocation here, `versionbar list --json` through uv, and
//! keeps what it prints as opaque JSON: it checks that the output is a JSON object with a
//! supported `schema_version` and reads nothing else (ADR-0006). Meaning, sorting and diffing
//! belong to the React UI (ADR-0007).

use std::{
    ffi::OsString,
    io::Read,
    path::{Path, PathBuf},
    process::{Child, Command, ExitStatus, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;

/// The only scan-result format this build understands. Equal to `SCHEMA_VERSION` in the core
/// (`tests/schema_version.rs` checks it against the generated schema). Any other value is a
/// breaking change the UI was not built for, so it is a failed scan, not data.
pub const SUPPORTED_SCHEMA_VERSION: u64 = 1;

/// The normal scan timeout (spec "Scan command"). The longer first-run timeout comes with the
/// setup screen in ticket 22.
pub const SCAN_TIMEOUT: Duration = Duration::from_secs(30);

/// How long to keep reading output after the process has exited or been killed. A grandchild
/// that inherited the pipes could otherwise keep the scan waiting forever. When that happens
/// the scan goes on with what arrived and the reader thread is left behind until the pipe
/// closes: a blocked read cannot be cancelled, and the core makes the same trade-off for the
/// tools it runs (`_DRAIN_SECONDS` in core/src/versionbar/system/real.py).
const DRAIN_TIMEOUT: Duration = Duration::from_secs(1);

const POLL: Duration = Duration::from_millis(20);

/// The release app has no console, so without this flag every process it starts would flash
/// one.
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Inherited uv settings that would change which project, Python, environment or dependency
/// set the fixed invocation uses, or contradict its flags. They are removed so a scan always
/// runs the bundled core as shipped. Network, index, cache and proxy settings are kept: a user
/// behind a mirror or proxy needs them for the first-run download. Checked against
/// `uv run --help` for uv 0.12; docs/app/bundled-core.md explains the groups.
const OVERRIDDEN_UV_VARIABLES: &[&str] = &[
    // Which Python: the invocation insists on a uv-managed one (AGENTS.md rule 7).
    "UV_PYTHON",
    "UV_MANAGED_PYTHON",
    "UV_NO_MANAGED_PYTHON",
    "UV_SYSTEM_PYTHON",
    "UV_PYTHON_PREFERENCE",
    // Which project and environment: the bundled core, in the app data folder.
    "UV_PROJECT",
    "UV_WORKING_DIR",
    "UV_NO_PROJECT",
    "UV_ISOLATED",
    // How the environment is synced: exactly the bundled lock file, without dev tools.
    "UV_LOCKED",
    "UV_FROZEN",
    "UV_NO_SYNC",
    "UV_NO_DEV",
    "UV_NO_DEFAULT_GROUPS",
    "UV_NO_GROUP",
    "UV_NO_EDITABLE",
    "UV_NO_SOURCES",
    "UV_NO_SOURCES_PACKAGE",
    // A dotenv file would load arbitrary variables into the core's process.
    "UV_ENV_FILE",
];

/// Finds uv afresh for every scan, so installing uv while the app runs needs no restart.
pub type FindUv = Box<dyn Fn() -> Option<PathBuf> + Send + Sync>;

/// Called with the new state whenever it changes; the app turns this into the
/// `scan-updated` event.
pub type Notify = Box<dyn Fn(&ShellState) + Send + Sync>;

pub struct ScanConfig {
    pub find_uv: FindUv,
    /// The bundled core project (the folder holding its `pyproject.toml` and `uv.lock`).
    pub project: PathBuf,
    /// Where uv keeps the core's Python environment: the app data folder, never the install
    /// folder, so it survives updates and needs no write access there (spec story 66).
    pub environment: PathBuf,
    pub timeout: Duration,
}

/// Everything the popup knows, as sent over IPC (`get_state` and the `scan-updated` event).
#[derive(Clone, Debug, Default, Serialize)]
pub struct ShellState {
    scanning: bool,
    /// The latest successful scan result, exactly as the core printed it.
    current: Option<Box<RawValue>>,
    /// The successful scan before `current`, so the UI can highlight changes.
    previous: Option<Box<RawValue>>,
    /// How the latest finished attempt went; `null` until the first one finishes.
    outcome: Option<Outcome>,
}

impl ShellState {
    pub fn scanning(&self) -> bool {
        self.scanning
    }
}

/// How one scan attempt ended. Ticket 22 adds a separate "setting up" state.
#[derive(Clone, Debug, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Outcome {
    Ok,
    /// uv was not found by any lookup. VersionBar never installs it (AGENTS.md hard rule 5).
    UvMissing,
    Failed {
        reason: FailureReason,
        /// One line for the user, in English.
        message: String,
        /// The core's (or uv's) stderr, decoded lossily and trimmed.
        stderr: String,
    },
}

#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FailureReason {
    /// uv could not be started at all.
    Launch,
    Timeout,
    /// uv or the core exited with a nonzero code, or how it ended could not be observed.
    Exit,
    /// stdout was not a JSON object.
    Malformed,
    /// A JSON object without a supported `schema_version`.
    Incompatible,
}

pub struct Scanner {
    config: ScanConfig,
    state: Mutex<ShellState>,
    notify: Notify,
}

impl Scanner {
    pub fn new(config: ScanConfig, notify: Notify) -> Self {
        Scanner {
            config,
            state: Mutex::default(),
            notify,
        }
    }

    pub fn state(&self) -> ShellState {
        self.state.lock().unwrap().clone()
    }

    /// Runs one scan and waits for it. Returns false without doing anything when a scan is
    /// already running, so overlapping requests never start a second core process.
    pub fn refresh(&self) -> bool {
        if !self.update(|state| {
            if state.scanning {
                return false;
            }
            state.scanning = true;
            true
        }) {
            return false;
        }

        let result = self.scan();
        self.update(|state| {
            state.scanning = false;
            match result {
                Ok(scan) => {
                    state.previous = state.current.take();
                    state.current = Some(scan);
                    state.outcome = Some(Outcome::Ok);
                }
                // A failed attempt keeps the last good results so the popup still has data.
                Err(outcome) => state.outcome = Some(outcome),
            }
            true
        });
        true
    }

    /// Applies `change` under the lock and announces the new state if `change` returns true.
    fn update(&self, change: impl FnOnce(&mut ShellState) -> bool) -> bool {
        let mut state = self.state.lock().unwrap();
        let changed = change(&mut state);
        if changed {
            // Announced while still locked, so listeners see the states in order.
            (self.notify)(&state);
        }
        changed
    }

    fn scan(&self) -> Result<Box<RawValue>, Outcome> {
        let uv = (self.config.find_uv)().ok_or(Outcome::UvMissing)?;
        let output = run_core(&uv, &self.config)?;
        if !output.status.success() {
            let code = output
                .status
                .code()
                .map_or_else(|| "no exit code".to_owned(), |code| format!("code {code}"));
            return Err(failed(
                FailureReason::Exit,
                format!("The scan failed ({code})."),
                &output.stderr,
            ));
        }
        check_scan(output.stdout)
            .map_err(|(reason, message)| failed(reason, message, &output.stderr))
    }
}

fn failed(reason: FailureReason, message: String, stderr: &[u8]) -> Outcome {
    Outcome::Failed {
        reason,
        message,
        stderr: String::from_utf8_lossy(stderr).trim().to_owned(),
    }
}

/// The only fields the shell ever reads from a scan result. Everything else is skipped
/// unread, which is what keeps the shell opaque.
#[derive(Deserialize)]
struct Envelope {
    schema_version: Option<serde_json::Value>,
}

fn check_scan(stdout: Vec<u8>) -> Result<Box<RawValue>, (FailureReason, String)> {
    let malformed = || {
        (
            FailureReason::Malformed,
            "The scan printed something that is not a scan result.".to_owned(),
        )
    };
    let text = String::from_utf8(stdout).map_err(|_| malformed())?;
    // Parsed once; the text is kept exactly as printed, minus surrounding whitespace.
    let scan = RawValue::from_string(text).map_err(|_| malformed())?;
    // serde would also accept a JSON array as `Envelope` (fields by position), so insist on
    // an object before looking inside.
    if !scan.get().starts_with('{') {
        return Err(malformed());
    }
    // Can still fail on valid JSON, for instance a repeated `schema_version` key.
    let envelope: Envelope = serde_json::from_str(scan.get()).map_err(|_| malformed())?;
    match envelope.schema_version {
        Some(version) if version.as_u64() == Some(SUPPORTED_SCHEMA_VERSION) => {}
        Some(version) => {
            return Err((
                FailureReason::Incompatible,
                format!(
                    "The scan result has schema_version {version}; this app supports {SUPPORTED_SCHEMA_VERSION}."
                ),
            ));
        }
        None => {
            return Err((
                FailureReason::Incompatible,
                "The scan result has no schema_version.".to_owned(),
            ));
        }
    }
    Ok(scan)
}

struct Output {
    status: ExitStatus,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
}

/// `uv run` with fixed arguments: the lock file as shipped (`--frozen`), no dev tools, and a
/// uv-managed Python only, never the system Python the core reports on (AGENTS.md rule 7).
fn core_command(uv: &Path, config: &ScanConfig) -> Command {
    let mut command = Command::new(uv);
    command
        .arg("run")
        .arg("--frozen")
        .arg("--no-dev")
        .arg("--managed-python")
        .arg("--project")
        .arg(&config.project)
        .args(["--", "versionbar", "list", "--json"])
        .env("UV_PROJECT_ENVIRONMENT", &config.environment)
        // Python would otherwise write __pycache__ folders next to the bundled sources, in
        // the install folder.
        .env("PYTHONPYCACHEPREFIX", config.environment.join("pycache"))
        // An activated virtualenv in the app's environment would only make uv warn.
        .env_remove("VIRTUAL_ENV")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for name in OVERRIDDEN_UV_VARIABLES {
        command.env_remove(name);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
}

fn run_core(uv: &Path, config: &ScanConfig) -> Result<Output, Outcome> {
    let mut child = core_command(uv, config).spawn().map_err(|error| {
        failed(
            FailureReason::Launch,
            format!("Could not start uv at {}: {error}", uv.display()),
            &[],
        )
    })?;
    let stdout = collect(child.stdout.take());
    let stderr = collect(child.stderr.take());

    let deadline = Instant::now() + config.timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() >= deadline => {
                return Err(stop(
                    child,
                    stderr,
                    FailureReason::Timeout,
                    format!(
                        "The scan did not finish within {} seconds.",
                        config.timeout.as_secs_f64()
                    ),
                ));
            }
            Ok(None) => thread::sleep(POLL),
            // Not a timeout: the scan may still be running, but its end can no longer be
            // observed, so it is stopped rather than left running unwatched.
            Err(error) => {
                return Err(stop(
                    child,
                    stderr,
                    FailureReason::Exit,
                    format!("Could not tell whether the scan finished: {error}"),
                ));
            }
        }
    };
    Ok(Output {
        status,
        stdout: stdout.finish(),
        stderr: stderr.finish(),
    })
}

/// Ends a scan that did not exit by itself, keeping whatever it wrote to stderr.
fn stop(mut child: Child, stderr: Collected, reason: FailureReason, message: String) -> Outcome {
    kill_tree(&mut child);
    failed(reason, message, &stderr.finish())
}

/// Output read on a background thread, so a full pipe never blocks the process.
struct Collected {
    buffer: Arc<Mutex<Vec<u8>>>,
    done: Option<thread::JoinHandle<()>>,
}

fn collect(pipe: Option<impl Read + Send + 'static>) -> Collected {
    let buffer: Arc<Mutex<Vec<u8>>> = Arc::default();
    let done = pipe.map(|mut pipe| {
        let buffer = buffer.clone();
        thread::spawn(move || {
            let mut chunk = [0u8; 8192];
            while let Ok(read @ 1..) = pipe.read(&mut chunk) {
                buffer.lock().unwrap().extend_from_slice(&chunk[..read]);
            }
        })
    });
    Collected { buffer, done }
}

impl Collected {
    /// Whatever arrived, waiting at most `DRAIN_TIMEOUT` for the pipe to close.
    fn finish(self) -> Vec<u8> {
        if let Some(done) = self.done {
            let deadline = Instant::now() + DRAIN_TIMEOUT;
            while !done.is_finished() && Instant::now() < deadline {
                thread::sleep(POLL);
            }
        }
        std::mem::take(&mut *self.buffer.lock().unwrap())
    }
}

/// Stops uv and everything it started (the core's Python and the tools it runs).
fn kill_tree(child: &mut Child) {
    #[cfg(windows)]
    {
        // taskkill from System32 by full path, so a stray taskkill on PATH is never run.
        if let Some(root) = std::env::var_os("SystemRoot") {
            let mut taskkill = Command::new(Path::new(&root).join("System32").join("taskkill.exe"));
            taskkill
                .args(["/F", "/T", "/PID", &child.id().to_string()])
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            use std::os::windows::process::CommandExt;
            taskkill.creation_flags(CREATE_NO_WINDOW);
            let _ = taskkill.status();
        }
    }
    // Covers non-Windows, and Windows if taskkill was unavailable; harmless if already gone.
    let _ = child.kill();
    let _ = child.wait();
}

/// Finds uv the way the spec orders it: PATH, then `UV_INSTALL_DIR`, then the default
/// user-local bin (`~/.local/bin`, where uv's installer puts it). The last two matter when
/// the app starts at login without the shell's PATH (spec story 65). `var` reads an
/// environment variable; tests pass their own.
pub fn find_uv(var: &dyn Fn(&str) -> Option<OsString>) -> Option<PathBuf> {
    let name = if cfg!(windows) { "uv.exe" } else { "uv" };
    let on_path = var("PATH")
        .into_iter()
        .flat_map(|path| std::env::split_paths(&path).collect::<Vec<_>>());
    let install_dir = var("UV_INSTALL_DIR").map(PathBuf::from);
    let home = var(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
        .map(|home| PathBuf::from(home).join(".local").join("bin"));
    on_path
        .chain(install_dir)
        .chain(home)
        // Relative (and empty) entries would depend on the working directory, which nobody
        // chose; the core skips them in PATH too.
        .filter(|dir| dir.is_absolute())
        .map(|dir| dir.join(name))
        .find(|candidate| candidate.is_file())
}
