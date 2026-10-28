//! Guardrail: the shell accepts exactly the scan-result version the bundled core prints.
//! `schema/output.schema.json` is generated from the core's models (ADR-0005), so a core bump
//! fails here until the shell (and the UI) are updated for the breaking change.

use std::{fs, path::Path};

use serde_json::Value;
use tray_shell::scan::SUPPORTED_SCHEMA_VERSION;

#[test]
fn supported_schema_version_matches_the_generated_schema() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../schema/output.schema.json");
    let text =
        fs::read_to_string(&path).unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
    let schema: Value = serde_json::from_str(&text).expect("output schema is valid JSON");
    let version = &schema["$defs"]["ScanResult"]["properties"]["schema_version"]["default"];

    assert_eq!(version.as_u64(), Some(SUPPORTED_SCHEMA_VERSION));
}
