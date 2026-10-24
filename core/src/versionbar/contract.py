"""The machine contracts generated from the Pydantic models (ADR 0005).

Two schemas come from here and are committed under `schema/` by `npm run gen`:

- the output schema: every JSON document a command prints with `--json`,
  which `versionbar schema` also prints;
- the definition schema: the TOML tool-definition format, which taplo checks
  the built-in definitions against.

Run as `python -m versionbar.contract` (what `npm run gen` does) to print both,
keyed by their file name under `schema/`.
"""

import json
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema, models_json_schema

from versionbar.capture import CaptureFailure, CaptureOutcome
from versionbar.definition import ToolDefinition
from versionbar.models import SCHEMA_VERSION, CheckResult, ScanResult

DIALECT = "https://json-schema.org/draft/2020-12/schema"

# Each command's `--json` output. A later command with its own result adds its
# model here rather than reshaping an existing one.
OUTPUT_MODELS: list[type[BaseModel]] = [ScanResult, CheckResult, CaptureOutcome, CaptureFailure]


class _Generator(GenerateJsonSchema):
    # Pydantic titles every field after its name ("Version Args"). The TS
    # generator turns each title into its own named type alias, so field titles
    # would flood the types with `type Id = string`; model titles stay.
    def field_title_should_be_set(self, schema: Any) -> bool:
        return False


def output_schema() -> dict[str, Any]:
    # Serialization mode: the schema describes what the CLI prints, where every
    # field is always present (`via`/`raw` as explicit null, `notes` as a list).
    # Only the shared `{"$defs": ...}` is kept; each model is reached through `anyOf` below.
    _, defs = models_json_schema(
        [(model, "serialization") for model in OUTPUT_MODELS], schema_generator=_Generator
    )
    return {
        "$schema": DIALECT,
        "title": "CommandOutput",
        "description": (
            f"Every document the CLI prints with --json. Scan results (list, show) carry "
            f"schema_version {SCHEMA_VERSION}, which changes only on breaking changes."
        ),
        "anyOf": [{"$ref": f"#/$defs/{model.__name__}"} for model in OUTPUT_MODELS],
        **defs,
    }


def definition_schema() -> dict[str, Any]:
    return {
        "$schema": DIALECT,
        **ToolDefinition.model_json_schema(mode="validation", schema_generator=_Generator),
    }


def generated_files() -> dict[str, dict[str, Any]]:
    return {
        "output.schema.json": output_schema(),
        "definition.schema.json": definition_schema(),
    }


if __name__ == "__main__":
    print(json.dumps(generated_files()))
