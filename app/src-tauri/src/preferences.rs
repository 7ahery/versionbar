//! The preferences query, `versionbar config --json` (ADR-0011): where the user's config file
//! is and the preferences it sets, as the core resolved them.
//!
//! The answer is held as opaque JSON and passed to the popup unchanged. Rust reads exactly two
//! fields from it, the documented exception to hard rule 2 (docs/app/preferences.md):
//! `config_path`, for the native "open config file" action, and `preferences.update_check`,
//! for the updater. Rust never reads the config file itself.

use std::{
    path::{Path, PathBuf},
    sync::Mutex,
    time::Duration,
};

use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;

use crate::scan::{
    FailureReason, Outcome, Query, ScanConfig, check_output, failed, malformed, run_core,
};

/// The core's exit code for a config file it cannot use. The query still prints a full answer
/// then: the path and the problems, with `preferences` null.
const INVALID_CONFIG_EXIT_CODE: i32 = 3;

/// Called with the new state after every query; the app turns this into the
/// `preferences-updated` event.
pub type Notify = Box<dyn Fn(&PreferencesState) + Send + Sync>;

/// What the popup gets over IPC (`get_preferences` and the `preferences-updated` event).
#[derive(Clone, Debug, Default, Serialize)]
pub struct PreferencesState {
    /// The latest answer the core gave, exactly as printed, including one for an invalid
    /// config (its `problems` say what to fix). A failed query keeps the previous answer.
    config: Option<Box<RawValue>>,
    /// How the latest query ended; `null` until the first one finishes. `ok` whenever the core
    /// answered, also for an invalid config.
    outcome: Option<Outcome>,
}

pub struct Preferences {
    known: Mutex<Known>,
    notify: Notify,
}

#[derive(Default)]
struct Known {
    state: PreferencesState,
    config_path: Option<PathBuf>,
    /// The last update setting a usable config gave since launch. Kept through failed queries
    /// and invalid configs, so a known "off" is never lost to a broken file or a hung uv.
    update_check: Option<bool>,
}

/// The two fields Rust reads. Everything else is skipped unread.
#[derive(Deserialize)]
struct Answer {
    config_path: String,
    preferences: Option<UpdateFlag>,
}

#[derive(Deserialize)]
struct UpdateFlag {
    update_check: bool,
}

/// A checked answer.
struct Read {
    raw: Box<RawValue>,
    config_path: PathBuf,
    /// None for an invalid config: the core could not say.
    update_check: Option<bool>,
}

impl Preferences {
    /// Knows nothing until the first query, so updates start disabled.
    pub fn new(notify: Notify) -> Self {
        Preferences {
            known: Mutex::default(),
            notify,
        }
    }

    pub fn state(&self) -> PreferencesState {
        self.known.lock().unwrap().state.clone()
    }

    /// Whether the app may check for updates: the last setting known since launch, and false
    /// if none is known. An unknown setting never means "enabled" (ADR-0011).
    pub fn update_check(&self) -> bool {
        self.known.lock().unwrap().update_check.unwrap_or(false)
    }

    /// The config file path the core resolved, whether or not the file exists; None until a
    /// query has answered.
    pub fn config_path(&self) -> Option<PathBuf> {
        self.known.lock().unwrap().config_path.clone()
    }

    /// Runs the query and announces the result. Called by the scanner before each scan, with
    /// that scan's uv and timeout, so it is never run twice at once.
    pub(crate) fn query(&self, uv: Option<&Path>, config: &ScanConfig, timeout: Duration) {
        let result = ask(uv, config, timeout);
        let mut known = self.known.lock().unwrap();
        match result {
            Ok(read) => {
                known.state.config = Some(read.raw);
                known.state.outcome = Some(Outcome::Ok);
                known.config_path = Some(read.config_path);
                if read.update_check.is_some() {
                    known.update_check = read.update_check;
                }
            }
            Err(outcome) => known.state.outcome = Some(outcome),
        }
        // Announced while still locked, so listeners see the states in order.
        (self.notify)(&known.state);
    }
}

fn ask(uv: Option<&Path>, config: &ScanConfig, timeout: Duration) -> Result<Read, Outcome> {
    let uv = uv.ok_or(Outcome::UvMissing)?;
    let output = run_core(uv, config, timeout, Query::Preferences)?;
    match output.status.code() {
        Some(0) => check(output.stdout, true)
            .map_err(|(reason, message)| failed(reason, message, &output.stderr)),
        // An answer for an invalid config is still worth keeping for its path and problems.
        // Output that is not one is reported as the failed exit it is.
        Some(INVALID_CONFIG_EXIT_CODE) => {
            let failure = output.exit_failure(Query::Preferences);
            check(output.stdout, false).map_err(|_| failure)
        }
        _ => Err(output.exit_failure(Query::Preferences)),
    }
}

/// `usable` is whether the core said the config is usable (exit 0); only then must the answer
/// carry an update setting, and only then is it believed.
fn check(stdout: Vec<u8>, usable: bool) -> Result<Read, (FailureReason, String)> {
    let raw = check_output(stdout, Query::Preferences)?;
    let answer: Answer =
        serde_json::from_str(raw.get()).map_err(|_| malformed(Query::Preferences))?;
    let update_check = if usable {
        let flag = answer
            .preferences
            .ok_or_else(|| malformed(Query::Preferences))?;
        Some(flag.update_check)
    } else {
        None
    };
    Ok(Read {
        raw,
        config_path: PathBuf::from(answer.config_path),
        update_check,
    })
}
