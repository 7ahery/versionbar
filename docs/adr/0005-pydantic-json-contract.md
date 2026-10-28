# Pydantic models are the JSON contract

Pydantic models in the core are the single source of truth for the ScanResult. The JSON Schema and TS types are generated and committed, and CI fails when either is stale, so the CLI and UI cannot drift. `schema_version` is an integer separate from the package version, bumped only on breaking changes.
