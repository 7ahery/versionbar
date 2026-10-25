# Capturing real command output

Tool detection is only as good as the evidence behind it. `versionbar debug capture` records what a tool's version command really printed, in a file the test suite's fake system replays directly. Contributors use it for fixtures, bug reporters attach its files to issues, and detector agents reach it through one CI workflow.

The command is hidden from `--help` on purpose: it is contributor tooling, not product surface.

## Capture on your own machine

```sh
uv run --project core versionbar debug capture <tool> [--source <provider>] [--out <folder>] [--json]
```

- `<tool>` is a tool id from a built-in definition (for example `git`). It runs exactly the definition's version command for the current OS, on the first match found on `PATH` that a scan would run: Microsoft Store placeholders and the scripts folder of the environment running VersionBar are skipped, as in a scan. Nothing is installed or modified. To capture an install that is not first on your PATH (for example a uv-managed Python on a machine whose bare `python` is a Store placeholder), run the command with `PATH` narrowed to its folder and say so in `provenance.notes`.
- `--source <provider>` (for example `--source nvm`) captures the first install that provider reports for the tool instead, wherever it is, and sets `provenance.notes` to say so. See [docs/providers.md](providers.md).
- The file is written to `--out` (default `versionbar-captures/`) as `<os>-<tool>-<version>.json`, for example `windows-git-2.55.0.windows.2.json`. The command prints the destination; with `--json` it prints `{"outcome": "captured", "tool", "destination", "exit_code"}`.
- A command that runs but fails (non-zero exit) is still captured, with its true exit status. That is evidence too.
- Failures write no file, so a failed capture never looks like a fixture. With `--json` the error is `{"outcome", "tool", "message"}`.
  - Exit status 2 (usage error, like `show`): `unknown-tool`; `unknown-source` for a `--source` that is no provider, or a provider that reports no installs of that tool; and `unsupported-os` for a known tool with no definition for this OS (message: `<id> is not available on <os>`) or a provider that does not run on it.
  - Exit status 1: `not-found` (not on `PATH`, or the provider reports no install), `timeout`, `launch-error` (including no exit status, and a `--source` provider that fails to list its installs), `write-failed`.

## File format (version 1)

One JSON file per capture:

| Field | Meaning |
| --- | --- |
| `format` | Always `1`. |
| `tool`, `args` | Tool id and the arguments after the executable; the fake system matches on `args`. |
| `exit_code` | The real exit status. |
| `stdout_b64`, `stderr_b64` | The raw bytes, base64-encoded. These are authoritative; decoding (including UTF-16 from WSL) is the engine's job. |
| `encoding` | Capture-time guess (`utf-8`, `utf-16`, `utf-16-le`) used only for the two text fields below. |
| `stdout_text`, `stderr_text` | Decoded for human readers and bug reports. Never read back by the fake. |
| `provenance` | `method`, `versionbar_version`, `os_id`, `os_description`, `resolved_path`, `command` (exact argv), `captured_at` (UTC), `runner` (CI image and run URL, or null), `notes`. On Windows, a path inside your profile folder is written as `%USERPROFILE%\...` in `resolved_path` and `command` (matched case-insensitively, whole folder names only), so the file does not carry your account name. |

The model is `CaptureFile` in `core/src/versionbar/capture.py`; the fake in `core/tests/fakes.py` loads it with that same model.

## Storage

Fixtures live under `core/tests/fixtures/<tool>/`; captures of installs a provider found (`--source`) under `core/tests/fixtures/<provider>/`. Name them `<os>-<tool>-<version>.json`, which is what the command already produces. Every tool and provider needs a real capture; never write output by hand. A hand-made seed is only acceptable when `provenance.notes` says which machine and command produced it.

## Capture on a clean Windows runner

The `Capture tool output` workflow (`.github/workflows/capture.yml`) is the single shared route for this. It runs on `windows-latest`, is dispatched by hand only, and never installs any tool, so a tool the runner image lacks yields a `not-found` outcome instead of a capture.

```sh
gh workflow run capture.yml -f tools="git node"            # tool ids, space or comma separated
gh workflow run capture.yml -f tools=mytool -f ref=my-branch   # draft definitions from a reviewed branch
gh run list --workflow capture.yml --limit 1               # find the run id
gh run watch <run-id>
gh run download <run-id> -n captures-<run-id>
```

GitHub returns 404 when you dispatch a workflow that is not on the default branch, even with `--ref`, so the workflow must be on `main` (it is). The `ref` input then chooses which code is checked out and run, so it is how a branch of draft definitions gets captured.

The job stays green whatever the capture outcomes are; read `outcomes/` rather than the job status. Only rejected inputs (no ids, or a malformed id) fail the job.

Tool ids must match `[a-z0-9][a-z0-9-]*`; anything else is rejected before any command runs. The artifact `captures-<run-id>` holds:

- `captures/`: one capture file per successful tool.
- `outcomes/<tool>.json`: the command's result for every requested tool, including `not-found`, `unknown-tool` and `timeout` failures.
- `outcomes/provenance.json`: workflow run URL, checked-out commit, requested ref, runner image name and version, and the fixed invocation used.

Copy the files you want into `core/tests/fixtures/<tool>/` and review them like any other change. Providers reuse the same command through `--source` on your own machine; the workflow does not take it, since runner images hold no version-manager installs and the workflow installs nothing.

## Attaching a capture to a bug report

Attach the `.json` file from `debug capture` to the issue. It contains the bytes needed to reproduce the problem plus the OS and resolved path. Your profile folder is already replaced by `%USERPROFILE%`, but an install elsewhere (or a tool that prints its own path) can still reveal names, so skim `provenance.resolved_path` and the `*_text` fields first.
