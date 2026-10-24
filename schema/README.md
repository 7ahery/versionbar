# Generated contracts

Everything in this folder except this README is generated. Do not edit it by hand.

| File | What it describes | Source |
|---|---|---|
| `output.schema.json` | Every document the CLI prints with `--json` (JSON Schema draft 2020-12). `versionbar schema` prints the same schema. | Pydantic models in `core/src/versionbar/models.py` and `capture.py` |
| `output.d.ts` | The same documents as TS types, imported by the UI as `import type { ScanResult } from "schema"`. | `output.schema.json` |
| `definition.schema.json` | The TOML tool-definition format. taplo checks every built-in definition against it. | `ToolDefinition` in `core/src/versionbar/definition.py` |

`npm run gen` at the repo root also writes `app/src/product.ts`, the UI's product-name constant, from `productName` in `app/src-tauri/tauri.conf.json`.

## Changing the contract

1. Change the Pydantic models. They are the single source of truth (ADR 0005). Docstrings on models and fields become schema descriptions and TS doc comments, so write them for consumers.
2. Run `npm run gen` and commit the regenerated files along with the model change.
3. `npm run lint` (and CI) runs `npm run lint:gen`, which fails when any generated file is stale.

A command that gets its own `--json` result adds its model to `OUTPUT_MODELS` in `core/src/versionbar/contract.py`. Don't reuse a model that has a different meaning, such as `ScanResult`, for an unrelated response.

## Compatibility and versioning

- A scan result (`list`, `show`), a check result (`check`) and a config result (`config`) carry `schema_version`, an integer kept separate from the package version. Consumers check it before reading further. Of a scan result the Rust shell reads nothing else; of a config result it reads only what docs/config.md lists for the app.
- `schema_version` changes only for breaking changes: a field is removed, renamed or retyped, a field becomes nullable, or an enum loses a value.
- Additions are not breaking and keep the version: a new field, or a new enum value such as a `status`, `platform` or capture `outcome`.
- So consumers must ignore fields they don't know, and must handle enum values they don't know, for example with a default branch that shows the value as-is. The generated TS types repeat this note on `ScanResult`, `ToolStatus` and `FailureOutcome`.
- The schema describes exactly what this version prints: unknown keys are forbidden and every field is required. So an older copy of the schema rejects output that only gained a field. To validate output, use the schema from the same version (`versionbar schema`).
- Every field is always printed. Optional values are explicit `null` (`via`, `raw`) or an empty list (`notes`), never omitted.
- `notes` holds human-readable diagnostics. Don't parse it.

## Tool definitions

Each built-in definition starts with a schema directive, so both taplo and TOML editors validate it:

```toml
#:schema ../../../../schema/definition.schema.json
```

The directive is needed because taplo 0.9.3 does not apply schemas through the `[[rule]]` include globs in `.taplo.toml`. The core tests check that every built-in carries the directive and validates against the schema. The loader enforces the same rules again at runtime, plus one check the schema can only approximate: `version_regex` must compile and contain a named group `(?P<version>...)`.
