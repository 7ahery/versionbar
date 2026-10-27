//! Open containing folder: shows an install in Explorer with the file selected.
//!
//! The path comes from the popup, and the shell cannot check it against the scan (it never
//! reads scan JSON, ADR-0006), so the path itself is checked instead: an existing local
//! path in a form Explorer cannot misread. Explorer only selects the item; nothing at the
//! path is ever run.

use std::{ffi::OsStr, fmt, path::Path, process::Command};

/// Why a path was not opened. The messages are shown to the user as they are.
#[derive(Debug, PartialEq, Eq)]
pub enum RevealError {
    /// Not a path of the accepted form (see `explorer_command`).
    NotALocalPath,
    /// A well-formed path where nothing exists now, for example an uninstalled tool.
    Gone,
    /// `SystemRoot` is unset, so Explorer cannot be found by full path.
    NoExplorer,
}

impl fmt::Display for RevealError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            RevealError::NotALocalPath => "This is not a drive-letter path.",
            RevealError::Gone => "This install no longer exists.",
            RevealError::NoExplorer => "Explorer could not be found.",
        })
    }
}

/// The Explorer invocation that opens the folder holding `path` with `path` selected.
///
/// Accepted: a drive-absolute path (`C:\...`, backslashes only) to an existing file, with no
/// control characters and none of `" * ? < > |`, and no colon except the drive's. That
/// shuts out relative paths (they would depend on the app's working folder), network and
/// device paths (`\\server\...`, `\\?\...`), which Explorer would open by contacting
/// something, alternate data streams, and quotes that could end the quoted path in
/// Explorer's argument. The form is checked before the disk is touched.
pub fn explorer_command(path: &str, system_root: Option<&OsStr>) -> Result<Command, RevealError> {
    if !is_plain_local_path(path) {
        return Err(RevealError::NotALocalPath);
    }
    if !Path::new(path).is_file() {
        return Err(RevealError::Gone);
    }
    let root = system_root.ok_or(RevealError::NoExplorer)?;
    let mut command = Command::new(Path::new(root).join("explorer.exe"));
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // Explorer reads `/select,"<path>"` with the quotes around the path only; Rust's own
        // quoting would wrap the whole argument, which Explorer misreads.
        command.raw_arg(format!("/select,\"{path}\""));
    }
    Ok(command)
}

pub(crate) fn is_plain_local_path(path: &str) -> bool {
    let mut chars = path.chars();
    let drive = matches!(
        (chars.next(), chars.next(), chars.next()),
        (Some(letter), Some(':'), Some('\\')) if letter.is_ascii_alphabetic()
    );
    drive
        && chars
            .all(|c| !c.is_control() && !matches!(c, '"' | '*' | '?' | '<' | '>' | '|' | ':' | '/'))
}
