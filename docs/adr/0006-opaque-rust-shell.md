# Rust shell is small and treats scan JSON as opaque

Rust owns lifecycle and narrowly scoped commands only, with no shell plugin, and it checks only `schema_version` of the scan JSON. The maintainer does not know Rust, so keeping Rust free of domain logic keeps AI-written Rust small and reviewable, and means contract changes never require Rust changes.
