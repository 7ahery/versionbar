//! Open containing folder: which paths the popup may hand the shell, and the exact Explorer
//! invocation built for them. The command is only built here, never started, so no Explorer
//! window opens during tests.
#![cfg(windows)]

use std::{
    ffi::OsStr,
    fs,
    path::{Path, PathBuf},
    sync::atomic::{AtomicUsize, Ordering},
};

use tray_shell::reveal::{RevealError, explorer_command};

const SYSTEM_ROOT: &str = r"C:\Windows";

/// A fresh, empty directory per test so parallel tests never share files.
fn scratch(name: &str) -> PathBuf {
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    let dir = std::env::temp_dir().join(format!(
        "tray-shell-reveal-{}-{}-{name}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::SeqCst)
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    dir
}

/// An existing file with a space in its folder name, like `C:\Program Files\Git\cmd\git.exe`.
fn install(name: &str) -> String {
    let dir = scratch(name).join("Program Files");
    fs::create_dir_all(&dir).unwrap();
    let file = dir.join("tool.exe");
    fs::write(&file, b"").unwrap();
    file.to_str().unwrap().to_owned()
}

fn build(path: &str) -> Result<std::process::Command, RevealError> {
    explorer_command(path, Some(OsStr::new(SYSTEM_ROOT)))
}

#[test]
fn selects_an_existing_install_in_explorer_from_the_windows_folder() {
    let path = install("selects");

    let command = build(&path).expect("a valid install path");

    assert_eq!(
        command.get_program(),
        Path::new(SYSTEM_ROOT).join("explorer.exe").as_os_str()
    );
    let args: Vec<&OsStr> = command.get_args().collect();
    // One argument, quoted as Explorer expects: Rust's own quoting would wrap the whole
    // `/select,...` in quotes, which Explorer does not understand.
    assert_eq!(args, [OsStr::new(&format!("/select,\"{path}\""))]);
}

#[test]
fn refuses_anything_but_a_plain_path_on_a_local_drive() {
    let real = install("refuses");
    let refused = [
        String::new(),
        r"tool.exe".to_owned(),
        r"Program Files\tool.exe".to_owned(),
        r"\Program Files\tool.exe".to_owned(),
        r"C:tool.exe".to_owned(),
        // Forward slashes: the core always prints backslashes, so this is not from a scan.
        real.replace('\\', "/"),
        // Network and device paths: Explorer would reach out to another machine or device.
        r"\\server\share\tool.exe".to_owned(),
        format!(r"\\?\{real}"),
        format!(r"\\.\{real}"),
        // A quote would end Explorer's quoted path and let the rest become more arguments.
        format!("{real}\" /root,\"C:\\"),
        // Control characters, wildcards and alternate data streams are never in a real path.
        format!("{real}\n"),
        real.replace("tool.exe", "*.exe"),
        format!("{real}:stream"),
        real.replace("tool.exe", "tool<1>.exe"),
        real.replace("tool.exe", "tool|x.exe"),
    ];
    for path in refused {
        assert_eq!(
            build(&path).err(),
            Some(RevealError::NotALocalPath),
            "{path:?} must be refused"
        );
    }
}

#[test]
fn reports_an_install_that_is_gone() {
    let gone = scratch("gone").join("tool.exe");

    assert_eq!(build(gone.to_str().unwrap()).err(), Some(RevealError::Gone));
}

#[test]
fn opens_only_files_never_folders() {
    // Install paths are executables; a folder never comes from a scan.
    let dir = scratch("folder");

    assert_eq!(build(dir.to_str().unwrap()).err(), Some(RevealError::Gone));
}

#[test]
fn needs_the_windows_folder_to_find_explorer() {
    let path = install("no-root");

    assert_eq!(
        explorer_command(&path, None).err(),
        Some(RevealError::NoExplorer)
    );
}
