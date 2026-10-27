//! Open config file: the tray menu's way to the user's config file.
//!
//! The path is the one the core reported in the preferences query (DEC-13, DEC-22), so Rust
//! never works out config locations or reads TOML. Nothing here takes input from the webview:
//! the menu item is the only caller.

use std::{
    ffi::OsStr,
    fmt, fs,
    io::{self, Write},
    path::Path,
    process::Command,
};

use crate::reveal;

/// Written into a new config file. Embedded from the core's own template so the two cannot
/// drift; tests/config_file.rs asserts the equality.
pub const STARTER_CONFIG: &str = include_str!("../../../core/src/versionbar/starter_config.toml");

/// Why the config file was not opened. The messages are for the log: the menu has no place to
/// show them.
#[derive(Debug, PartialEq, Eq)]
pub enum ConfigError {
    /// No preferences query has answered yet, so the path is unknown.
    PathUnknown,
    /// The reported path is not a drive-letter path to a `.toml` file.
    NotAConfigPath,
    /// The file could not be created, for example because the folder is read-only.
    CannotCreate,
    /// `SystemRoot` is unset, so Explorer cannot be found by full path.
    NoExplorer,
    /// Explorer was found but the launch failed.
    CannotStart,
}

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            ConfigError::PathUnknown => "The config file location is not known yet.",
            ConfigError::NotAConfigPath => "The config file path is not a drive-letter .toml path.",
            ConfigError::CannotCreate => "The config file could not be created.",
            ConfigError::NoExplorer => "Explorer could not be found.",
            ConfigError::CannotStart => "Explorer could not be started.",
        })
    }
}

/// Makes sure the config file exists, then returns the Explorer invocation that opens it.
///
/// An absent file is created from `starter`; an existing one is left exactly as it is (it is
/// never opened for writing, so it cannot be truncated, even if it appears between the check
/// and the write). The path is checked before the disk is touched, with the same plain-local
/// rules as `reveal`, plus a `.toml` extension: Explorer *runs* what it is given, and a
/// config path from the environment must not be able to name a program.
pub fn open_command(
    config_path: Option<&Path>,
    starter: &str,
    system_root: Option<&OsStr>,
) -> Result<Command, ConfigError> {
    let path = config_path.ok_or(ConfigError::PathUnknown)?;
    let text = path.to_str().ok_or(ConfigError::NotAConfigPath)?;
    let is_toml = path
        .extension()
        .is_some_and(|ext| ext.eq_ignore_ascii_case("toml"));
    if !is_toml || !reveal::is_plain_local_path(text) {
        return Err(ConfigError::NotAConfigPath);
    }
    let root = system_root.ok_or(ConfigError::NoExplorer)?;
    create_if_absent(path, starter)?;

    let mut command = Command::new(Path::new(root).join("explorer.exe"));
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // As in `reveal`: Explorer wants the quotes around the path alone.
        command.raw_arg(format!("\"{text}\""));
    }
    Ok(command)
}

fn create_if_absent(path: &Path, starter: &str) -> Result<(), ConfigError> {
    if let Some(folder) = path.parent() {
        fs::create_dir_all(folder).map_err(|_| ConfigError::CannotCreate)?;
    }
    // `create_new` fails if anything exists at the path: that is the create-only guarantee.
    match fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
    {
        Ok(mut file) => file.write_all(starter.as_bytes()).map_err(|_| {
            // The file is ours (`create_new` succeeded). A partial one would never be
            // repaired, since later calls see an existing file and leave it alone.
            drop(file);
            let _ = fs::remove_file(path);
            ConfigError::CannotCreate
        }),
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists && path.is_file() => Ok(()),
        Err(_) => Err(ConfigError::CannotCreate),
    }
}
