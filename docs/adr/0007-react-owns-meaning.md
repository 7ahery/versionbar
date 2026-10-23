# The React UI owns all meaning

Parsing through generated types, diffing current against previous, sorting, search, the missing-tools section and per-install actions live in the React UI, fed by one JSON blob from Rust with no state library. This is the other half of ADR-0006: logic lives where the maintainer and the UI tests can reach it.
