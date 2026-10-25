//! Running the bundled core and holding its results (spec "Scan command", "State ownership").
//!
//! The shell runs the bundled core with one of exactly two fixed argument sets (`Query`): the
//! scan, `versionbar list --json`, and the preferences query, `versionbar config --json`
//! (ADR-0011, read in `preferences.rs`). It keeps what the scan prints as opaque JSON: it
//! checks that the output is a JSON object with a supported `schema_version` and reads nothing
//! else (ADR-0006). Meaning, sorting and diffing belong to the React UI (ADR-0007).

use std::{
    ffi::OsString,
    io::Read,
    path::{Path, PathBuf},
    process::{Child, Command, ExitStatus, Stdio},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::{Duration, Instant},
};

use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;

use crate::{preferences::Preferences, saved};

/// The only scan-result format this build understands. Equal to `SCHEMA_VERSION` in the core
/// (`tests/schema_version.rs` checks it against the generated schema). Any other value is a
/// breaking change the UI was not built for, so it is a failed scan, not data.
pub const SUPPORTED_SCHEMA_VERSION: u64 = 1;

/// The normal scan timeout (spec "Scan command").
pub const SCAN_TIMEOUT: Duration = Duration::from_secs(30);

/// The first run has to create the core's environment, and uv may download a managed Python
/// and the core's dependencies to do so, which can take far longer than a scan.
pub const FIRST_RUN_TIMEOUT: Duration = Duration::from_secs(180);

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
pub(crate) const CREATE_NO_WINDOW: u32 = 0x0800_0000;

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

/// Inherited Python settings that would point the core's interpreter at other standard
/// library or package folders, or run extra code in it. Settings that only tune behaviour
/// (encoding, warnings, optimisation) are left alone: the core sets its own output encoding.
const OVERRIDDEN_PYTHON_VARIABLES: &[&str] = &[
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONPLATLIBDIR",
    "PYTHONUSERBASE",
    "PYTHONEXECUTABLE",
    "PYTHONSTARTUP",
    "PYTHONINSPECT",
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
    /// Used instead of `timeout` while `environment` does not exist yet.
    pub first_run_timeout: Duration,
    /// Where the last two successful results are saved, so they survive a restart.
    pub state_file: PathBuf,
}

/// Everything the popup knows, as sent over IPC (`get_state` and the `scan-updated` event).
#[derive(Clone, Debug, Default, Serialize)]
pub struct ShellState {
    scanning: bool,
    /// True while a scan is the first run, which creates the core's environment and may
    /// download Python and packages. Only ever true together with `scanning`. A separate
    /// flag rather than an outcome: it describes work in progress, not how an attempt ended.
    setting_up: bool,
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

    /// True when the latest finished attempt found no uv.
    pub fn uv_missing(&self) -> bool {
        matches!(self.outcome, Some(Outcome::UvMissing))
    }
}

/// How one scan attempt ended.
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
    /// True from the moment the environment folder is found missing until a scan succeeds.
    /// A first run that times out can leave a half-built folder behind; without this the
    /// retry would count as an ordinary scan and get 30 seconds for the rest of the download.
    unsettled: AtomicBool,
    /// A refresh was asked for while a scan ran. Only changed under the state lock.
    queued: AtomicBool,
    /// Reread before every scan, so every refresh (popup, tray menu, schedule) also picks up
    /// config changes, and never runs a second uv process alongside the scan.
    preferences: Option<Arc<Preferences>>,
}

/// What one scan was started with, fixed before it is announced.
struct Job {
    uv: Option<PathBuf>,
    first_run: bool,
}

impl Scanner {
    /// Starts from the results saved by the last session, if there are usable ones. Nothing
    /// is scanned here; the caller decides when the first scan runs.
    pub fn new(config: ScanConfig, notify: Notify) -> Self {
        let mut state = ShellState::default();
        if let Some(saved) = saved::load(&config.state_file) {
            state.current = Some(saved.current);
            state.previous = saved.previous;
        }
        Scanner {
            config,
            state: Mutex::new(state),
            notify,
            unsettled: AtomicBool::new(false),
            queued: AtomicBool::new(false),
            preferences: None,
        }
    }

    /// Makes every scan job query the preferences first. Before the scan, so the very first
    /// job at launch learns the update setting without waiting for a full scan.
    pub fn with_preferences(mut self, preferences: Arc<Preferences>) -> Self {
        self.preferences = Some(preferences);
        self
    }

    pub fn state(&self) -> ShellState {
        self.state.lock().unwrap().clone()
    }

    /// Runs a scan and waits for it. Scans never overlap: a request made while one runs only
    /// returns false, and the call that owns the running scan does one more scan when it
    /// ends, because the request may follow a config change the running scan missed. Any
    /// number of requests made during one scan share that one extra scan. Returns true when
    /// this call ran the scans.
    pub fn refresh(&self) -> bool {
        // Looked up before anything is announced: an absent uv must go straight to "uv
        // missing" without a flash of the setup screen.
        let uv = (self.config.find_uv)();
        let mut job = None;
        self.update(|state| {
            if state.scanning {
                self.queued.store(true, Ordering::SeqCst);
                return false;
            }
            job = Some(self.start(state, uv));
            true
        });
        let Some(mut job) = job else {
            return false;
        };

        loop {
            if let Some(preferences) = &self.preferences {
                // Same uv, timeout and environment as the scan: on a first run this query
                // may be the one that builds the environment.
                preferences.query(job.uv.as_deref(), &self.config, self.timeout(job.first_run));
            }
            let result = self.scan(job.uv, job.first_run);
            if let Ok(scan) = &result {
                // Saved before the new results are announced, while this scan still holds
                // the claim: no other scan can save in between, so the file always ends up
                // with the latest pair, and the current result read here cannot change
                // meanwhile.
                let previous = self.state.lock().unwrap().current.clone();
                // Best effort: a disk that cannot be written must not cost the user the fresh
                // results, which stay in memory; the next successful scan tries again.
                let _ = saved::save(&self.config.state_file, scan, previous.as_deref());
            }
            // The extra scan's uv is looked up outside the lock like the first one's. Only a
            // request that lands in the instant between this check and the lock below pays
            // for a lookup under the lock.
            let mut uv_ahead = self
                .queued
                .load(Ordering::SeqCst)
                .then(|| (self.config.find_uv)());
            let mut next = None;
            self.update(|state| {
                state.scanning = false;
                state.setting_up = false;
                match result {
                    Ok(scan) => {
                        state.previous = state.current.take();
                        state.current = Some(scan);
                        state.outcome = Some(Outcome::Ok);
                        self.unsettled.store(false, Ordering::SeqCst);
                    }
                    // A failed attempt keeps the last good results so the popup still has
                    // data.
                    Err(outcome) => state.outcome = Some(outcome),
                }
                // Started in the same step that ends the scan, so no other refresh can slip
                // in between and the popup sees one continuous scan.
                if self.queued.swap(false, Ordering::SeqCst) {
                    let uv = uv_ahead.take().unwrap_or_else(|| (self.config.find_uv)());
                    next = Some(self.start(state, uv));
                }
                true
            });
            match next {
                Some(following) => job = following,
                None => return true,
            }
        }
    }

    /// Claims the scan for a new run. Called under the lock, so a refresh never reads
    /// `unsettled` while the previous scan is still settling it, and only a scan that really
    /// runs may start the unsettled period. The timeout is fixed here too, so a folder that
    /// appears while the scan runs does not change it.
    fn start(&self, state: &mut ShellState, uv: Option<PathBuf>) -> Job {
        let first_run = self.unsettled.load(Ordering::SeqCst) || !self.config.environment.exists();
        if first_run {
            self.unsettled.store(true, Ordering::SeqCst);
        }
        state.scanning = true;
        state.setting_up = uv.is_some() && first_run;
        Job { uv, first_run }
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

    fn timeout(&self, first_run: bool) -> Duration {
        if first_run {
            self.config.first_run_timeout
        } else {
            self.config.timeout
        }
    }

    fn scan(&self, uv: Option<PathBuf>, first_run: bool) -> Result<Box<RawValue>, Outcome> {
        let uv = uv.ok_or(Outcome::UvMissing)?;
        let output = run_core(&uv, &self.config, self.timeout(first_run), Query::Scan)?;
        if !output.status.success() {
            return Err(output.exit_failure(Query::Scan));
        }
        check_output(output.stdout, Query::Scan)
            .map_err(|(reason, message)| failed(reason, message, &output.stderr))
    }
}

/// How often the tray rescans on its own (spec story 52).
pub const REFRESH_INTERVAL: Duration = Duration::from_secs(30 * 60);

/// Scans now, then again `interval` after each scan ends, on a thread of its own, so nothing
/// waits for it. `after` runs once a scan this schedule started has ended. A tick that lands
/// while another scan runs is answered like any other refresh (see `Scanner::refresh`). The
/// thread holds the scanner only while scanning and stops once every other handle on it is
/// gone, which only happens in tests.
pub fn refresh_every(
    scanner: &Arc<Scanner>,
    interval: Duration,
    after: impl Fn(&Scanner) + Send + 'static,
) -> thread::JoinHandle<()> {
    let scanner = Arc::downgrade(scanner);
    thread::spawn(move || {
        loop {
            let Some(strong) = scanner.upgrade() else {
                return;
            };
            if strong.refresh() {
                after(&strong);
            }
            drop(strong);
            thread::sleep(interval);
        }
    })
}

pub(crate) fn failed(reason: FailureReason, message: String, stderr: &[u8]) -> Outcome {
    Outcome::Failed {
        reason,
        message,
        stderr: String::from_utf8_lossy(stderr).trim().to_owned(),
    }
}

/// The only field the shell reads from a scan result. Everything else is skipped unread,
/// which is what keeps the shell opaque. The preferences answer shares the same
/// `schema_version` counter.
#[derive(Deserialize)]
struct Envelope {
    schema_version: Option<serde_json::Value>,
}

pub(crate) fn malformed(query: Query) -> (FailureReason, String) {
    (
        FailureReason::Malformed,
        format!(
            "The {} printed something that is not a {}.",
            query.name(),
            query.result_name()
        ),
    )
}

/// The output kept exactly as printed, minus surrounding whitespace, once it passes
/// `check_envelope`.
pub(crate) fn check_output(
    stdout: Vec<u8>,
    query: Query,
) -> Result<Box<RawValue>, (FailureReason, String)> {
    let text = String::from_utf8(stdout).map_err(|_| malformed(query))?;
    let output = RawValue::from_string(text).map_err(|_| malformed(query))?;
    check_envelope(&output, query)?;
    Ok(output)
}

/// Accepts a JSON object with the supported `schema_version`, reading nothing else. Also
/// applied to saved results, which may come from another build.
pub(crate) fn check_envelope(
    output: &RawValue,
    query: Query,
) -> Result<(), (FailureReason, String)> {
    // serde would also accept a JSON array as `Envelope` (fields by position), so insist on
    // an object before looking inside.
    if !output.get().starts_with('{') {
        return Err(malformed(query));
    }
    // Can still fail on valid JSON, for instance a repeated `schema_version` key.
    let envelope: Envelope = serde_json::from_str(output.get()).map_err(|_| malformed(query))?;
    let result = query.result_name();
    match envelope.schema_version {
        Some(version) if version.as_u64() == Some(SUPPORTED_SCHEMA_VERSION) => {}
        Some(version) => {
            return Err((
                FailureReason::Incompatible,
                format!(
                    "The {result} has schema_version {version}; this app supports {SUPPORTED_SCHEMA_VERSION}."
                ),
            ));
        }
        None => {
            return Err((
                FailureReason::Incompatible,
                format!("The {result} has no schema_version."),
            ));
        }
    }
    Ok(())
}

/// The only two things the shell ever asks the core (ADR-0011). Each is a fixed argument
/// set; nothing from the webview or anywhere else is ever added to it.
#[derive(Clone, Copy)]
pub(crate) enum Query {
    /// `versionbar list --json`
    Scan,
    /// `versionbar config --json`
    Preferences,
}

impl Query {
    fn arguments(self) -> [&'static str; 2] {
        match self {
            Query::Scan => ["list", "--json"],
            Query::Preferences => ["config", "--json"],
        }
    }

    /// How the user-facing messages name it.
    fn name(self) -> &'static str {
        match self {
            Query::Scan => "scan",
            Query::Preferences => "preferences query",
        }
    }

    /// How the user-facing messages name what it prints.
    fn result_name(self) -> &'static str {
        match self {
            Query::Scan => "scan result",
            Query::Preferences => "config result",
        }
    }
}

pub(crate) struct Output {
    pub(crate) status: ExitStatus,
    pub(crate) stdout: Vec<u8>,
    pub(crate) stderr: Vec<u8>,
}

impl Output {
    /// The failure for a nonzero exit, carrying stderr.
    pub(crate) fn exit_failure(&self, query: Query) -> Outcome {
        let code = self
            .status
            .code()
            .map_or_else(|| "no exit code".to_owned(), |code| format!("code {code}"));
        failed(
            FailureReason::Exit,
            format!("The {} failed ({code}).", query.name()),
            &self.stderr,
        )
    }
}

/// `uv run` with fixed arguments: the lock file as shipped (`--frozen`), no dev tools, and a
/// uv-managed Python only, never the system Python the core reports on (AGENTS.md rule 7).
fn core_command(uv: &Path, config: &ScanConfig, query: Query) -> Command {
    let mut command = Command::new(uv);
    command
        .arg("run")
        .arg("--frozen")
        .arg("--no-dev")
        .arg("--managed-python")
        .arg("--project")
        .arg(&config.project)
        .args(["--", "versionbar"])
        .args(query.arguments())
        .env("UV_PROJECT_ENVIRONMENT", &config.environment)
        // Python would otherwise write __pycache__ folders next to the bundled sources, in
        // the install folder.
        .env("PYTHONPYCACHEPREFIX", config.environment.join("pycache"))
        // An activated virtualenv in the app's environment would only make uv warn.
        .env_remove("VIRTUAL_ENV")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for name in OVERRIDDEN_UV_VARIABLES
        .iter()
        .chain(OVERRIDDEN_PYTHON_VARIABLES)
    {
        command.env_remove(name);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
}

/// Runs one fixed query and collects its output. Launch failures and timeouts are outcomes
/// here; how an exit code and stdout are judged is up to the caller.
pub(crate) fn run_core(
    uv: &Path,
    config: &ScanConfig,
    timeout: Duration,
    query: Query,
) -> Result<Output, Outcome> {
    let mut child = core_command(uv, config, query).spawn().map_err(|error| {
        failed(
            FailureReason::Launch,
            format!("Could not start uv at {}: {error}", uv.display()),
            &[],
        )
    })?;
    let stdout = collect(child.stdout.take());
    let stderr = collect(child.stderr.take());

    let deadline = Instant::now() + timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() >= deadline => {
                return Err(stop(
                    child,
                    stderr,
                    FailureReason::Timeout,
                    format!(
                        "The {} did not finish within {} seconds.",
                        query.name(),
                        timeout.as_secs_f64()
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
                    format!(
                        "Could not tell whether the {} finished: {error}",
                        query.name()
                    ),
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
            if let Ok(mut taskkill) = taskkill.spawn() {
                // Bounded like the core's own taskkill (`_DRAIN_SECONDS`): a hung taskkill
                // must not hold up the scan. A slow one is stopped and the direct kill below
                // still runs.
                let deadline = Instant::now() + DRAIN_TIMEOUT;
                while matches!(taskkill.try_wait(), Ok(None)) && Instant::now() < deadline {
                    thread::sleep(POLL);
                }
                if matches!(taskkill.try_wait(), Ok(None)) {
                    let _ = taskkill.kill();
                }
            }
        }
    }
    // Covers non-Windows, and Windows if taskkill was unavailable or too slow; harmless if already gone.
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
