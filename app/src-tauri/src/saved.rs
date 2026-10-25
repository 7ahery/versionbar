//! The last two successful scan results on disk, so the popup has data right after login,
//! before the first scan of the session finishes (spec story 53).
//!
//! One file holds both results, so the pair is always replaced together. The scans inside
//! stay opaque text exactly as the core printed them; the only things read back are this
//! file's own `format` and each scan's `schema_version` (ADR-0006). A file that is missing,
//! damaged, from another format or holding an unsupported scan is ignored as a whole, and the
//! next successful scan replaces it.

use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
};

use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;

/// Version of this file's own layout. Unrelated to the scans' `schema_version`: it changes
/// only if the wrapper changes.
const FORMAT: u64 = 1;

/// The two results as they were last saved.
pub(crate) struct Pair {
    pub current: Box<RawValue>,
    pub previous: Option<Box<RawValue>>,
}

#[derive(Serialize)]
struct Written<'a> {
    format: u64,
    current: &'a RawValue,
    previous: Option<&'a RawValue>,
}

#[derive(Deserialize)]
struct Read {
    format: u64,
    current: Box<RawValue>,
    previous: Option<Box<RawValue>>,
}

/// The saved pair, or `None` when there is nothing usable on disk.
pub(crate) fn load(file: &Path) -> Option<Pair> {
    let text = fs::read_to_string(file).ok()?;
    let read: Read = serde_json::from_str(&text).ok()?;
    if read.format != FORMAT || !supported(&read.current) {
        return None;
    }
    if read
        .previous
        .as_deref()
        .is_some_and(|previous| !supported(previous))
    {
        return None;
    }
    Some(Pair {
        current: read.current,
        previous: read.previous,
    })
}

fn supported(scan: &RawValue) -> bool {
    crate::scan::check_envelope(scan).is_ok()
}

/// Replaces the saved pair. The new content goes to a temporary file next to the real one,
/// which is then renamed over it: a crash or power cut mid-write leaves either the old pair
/// or the new one, never half a file.
pub(crate) fn save(
    file: &Path,
    current: &RawValue,
    previous: Option<&RawValue>,
) -> std::io::Result<()> {
    if let Some(dir) = file.parent() {
        fs::create_dir_all(dir)?;
    }
    let text = serde_json::to_vec(&Written {
        format: FORMAT,
        current,
        previous,
    })?;
    let temporary = temporary(file);
    let mut out = fs::File::create(&temporary)?;
    out.write_all(&text)?;
    // On disk before the rename, or a crash could leave the renamed file empty.
    out.sync_all()?;
    drop(out);
    fs::rename(&temporary, file)
}

/// `scan-state.json` becomes `scan-state.json.tmp`. A leftover one from an interrupted
/// write is never read and is overwritten by the next save.
fn temporary(file: &Path) -> PathBuf {
    let mut name = file.as_os_str().to_owned();
    name.push(".tmp");
    PathBuf::from(name)
}
