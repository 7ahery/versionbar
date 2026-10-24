//! Which inherited `UV_*` variables reach the fixed core invocation. A test binary of its own
//! because it sets variables on the test process, which would leak into the other scan tests.

use std::{fs, path::PathBuf, time::Duration};

use tray_shell::scan::{ScanConfig, Scanner, ShellState};

/// Variables that would change which project, Python, environment or dependency set the scan
/// uses. The shell must not pass them on.
const OVERRIDES: &[&str] = &[
    "UV_PYTHON",
    "UV_MANAGED_PYTHON",
    "UV_NO_MANAGED_PYTHON",
    "UV_SYSTEM_PYTHON",
    "UV_PYTHON_PREFERENCE",
    "UV_PROJECT",
    "UV_WORKING_DIR",
    "UV_NO_PROJECT",
    "UV_ISOLATED",
    "UV_LOCKED",
    "UV_FROZEN",
    "UV_NO_SYNC",
    "UV_NO_DEV",
    "UV_NO_DEFAULT_GROUPS",
    "UV_NO_GROUP",
    "UV_NO_EDITABLE",
    "UV_NO_SOURCES",
    "UV_NO_SOURCES_PACKAGE",
    "UV_ENV_FILE",
];

/// Network, cache and index settings a user may need (a company mirror, a proxy, an offline
/// machine). These must still reach uv.
const KEPT: &[&str] = &[
    "UV_INDEX_URL",
    "UV_DEFAULT_INDEX",
    "UV_CACHE_DIR",
    "UV_OFFLINE",
    "UV_PYTHON_INSTALL_MIRROR",
    "UV_NATIVE_TLS",
];

#[test]
fn settings_that_would_redirect_the_scan_are_not_passed_to_uv() {
    let dir = std::env::temp_dir().join(format!("tray-shell-test-{}-env", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    for name in OVERRIDES.iter().chain(KEPT) {
        // SAFETY: the only test in this binary, set before any thread or child starts.
        unsafe { std::env::set_var(name, "set-by-test") };
    }

    let record = dir.join("env.txt");
    let uv: PathBuf = if cfg!(windows) {
        let path = dir.join("uv.cmd");
        fs::write(
            &path,
            format!(
                "@echo off\r\nset UV_ > \"{}\"\r\nexit /b 1\r\n",
                record.display()
            ),
        )
        .unwrap();
        path
    } else {
        let path = dir.join("uv");
        fs::write(
            &path,
            format!("#!/bin/sh\nenv > '{}'\nexit 1\n", record.display()),
        )
        .unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
        }
        path
    };
    let scanner = Scanner::new(
        ScanConfig {
            find_uv: Box::new(move || Some(uv.clone())),
            project: dir.join("core"),
            environment: dir.join("core-env"),
            timeout: Duration::from_secs(30),
        },
        Box::new(|_: &ShellState| {}),
    );

    scanner.refresh();

    let seen: Vec<String> = fs::read_to_string(&record)
        .unwrap()
        .lines()
        .filter_map(|line| line.split_once('=').map(|(name, _)| name.to_owned()))
        .collect();
    for name in OVERRIDES {
        assert!(
            !seen.iter().any(|s| s == name),
            "{name} reached uv: {seen:?}"
        );
    }
    for name in KEPT {
        assert!(
            seen.iter().any(|s| s == name),
            "{name} did not reach uv: {seen:?}"
        );
    }
    // Set by the shell itself, so the environment is the app's own.
    assert!(
        seen.iter().any(|s| s == "UV_PROJECT_ENVIRONMENT"),
        "{seen:?}"
    );
}
