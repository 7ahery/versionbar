//! Open config file: create-only starter template and the Explorer invocation. The command is
//! only built, never started, so no Explorer window opens during tests.
#![cfg(windows)]

use std::{
    ffi::OsStr,
    fs,
    path::{Path, PathBuf},
    sync::atomic::{AtomicUsize, Ordering},
};

use tray_shell::config_file::{ConfigError, STARTER_CONFIG, open_command};

const SYSTEM_ROOT: &str = r"C:\Windows";

fn scratch(name: &str) -> PathBuf {
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    let dir = std::env::temp_dir().join(format!(
        "tray-shell-config-{}-{}-{name}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::SeqCst)
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    dir
}

fn build(path: Option<&Path>) -> Result<std::process::Command, ConfigError> {
    open_command(path, "starter text\n", Some(OsStr::new(SYSTEM_ROOT)))
}

#[test]
fn embedded_starter_equals_the_core_template() {
    let file = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../core/src/versionbar/starter_config.toml");

    assert_eq!(STARTER_CONFIG, fs::read_to_string(file).unwrap());
}

#[test]
fn creates_the_starter_when_absent_and_opens_it_from_the_windows_folder() {
    let path = scratch("absent").join("versionbar").join("config.toml");

    let command = build(Some(&path)).expect("a valid config path");

    assert_eq!(fs::read_to_string(&path).unwrap(), "starter text\n");
    assert_eq!(
        command.get_program(),
        OsStr::new(&format!(r"{SYSTEM_ROOT}\explorer.exe"))
    );
}

#[test]
fn leaves_an_existing_file_unchanged() {
    let path = scratch("existing").join("config.toml");
    fs::write(&path, "my = \"edits\"\n").unwrap();

    build(Some(&path)).expect("an existing config opens");

    assert_eq!(fs::read_to_string(&path).unwrap(), "my = \"edits\"\n");
}

#[test]
fn an_empty_existing_file_is_not_replaced_by_the_starter() {
    let path = scratch("empty").join("config.toml");
    fs::write(&path, "").unwrap();

    build(Some(&path)).unwrap();

    assert_eq!(fs::read_to_string(&path).unwrap(), "");
}

#[test]
fn reports_an_unknown_path_without_touching_anything() {
    assert_eq!(build(None).unwrap_err(), ConfigError::PathUnknown);
}

#[test]
fn refuses_paths_that_are_not_plain_local_toml_files() {
    let dir = scratch("refused");
    for bad in [
        r"relative\config.toml".to_owned(),
        r"\\server\share\config.toml".to_owned(),
        dir.join("tool.exe").to_str().unwrap().to_owned(),
        format!("{}:stream.toml", dir.join("config.toml").to_str().unwrap()),
    ] {
        assert_eq!(
            build(Some(Path::new(&bad))).unwrap_err(),
            ConfigError::NotAConfigPath,
            "{bad}"
        );
    }
    assert_eq!(fs::read_dir(&dir).unwrap().count(), 0);
}

#[test]
fn reports_a_missing_system_root() {
    let path = scratch("noroot").join("config.toml");

    let error = open_command(Some(&path), "x", None).unwrap_err();

    assert_eq!(error, ConfigError::NoExplorer);
    assert!(!path.exists());
}
