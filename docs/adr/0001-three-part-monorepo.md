# Three-part monorepo with one shared version

VersionBar is one repository with a Python core, a Tauri app (Rust shell plus React/TS UI) and generated schema artifacts. They share one version number with the core's package metadata as the source of truth, so a release can never ship a mismatched CLI and UI. Separate repositories were rejected because the JSON contract changes across all three together.
