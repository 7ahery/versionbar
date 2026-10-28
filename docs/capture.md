# Capturing real command output

Tool detection is only as good as the evidence behind it. `versionbar debug capture` records what a tool's version command really printed, in a file the test suite's fake system replays directly. Contributors use it for fixtures, bug reporters attach its files to issues, and detector agents reach it through one CI workflow.

The command is hidden from `--help` on purpose: it is contributor tooling, not product surface.

## Capture on your own machine

```sh
uv run --project core versionbar debug capture <tool> [--source <provider>] [--timeout <seconds>] [--out <folder>] [--json]
```

- `<tool>` is a tool id from a built-in definition (for example `git`). It runs exactly the definition's version command for the current OS, on the first match found on `PATH` that a scan would run: Microsoft Store placeholders and the scripts folder of the environment running VersionBar are skipped, as in a scan. Nothing is installed or modified. To capture an install that is not first on your PATH (for example a uv-managed Python on a machine whose bare `python` is a Store placeholder), run the command with `PATH` narrowed to its folder and say so in `provenance.notes`.
- `--source <provider>` (for example `--source nvm`) captures what that provider reads instead: its listing command when it declares one (such as `dotnet --list-sdks` or `py -0p`), otherwise the first install it reports for the tool, wherever it is. `provenance.notes` says which. See [docs/providers.md](providers.md).
- `--timeout <seconds>` (default 5, the scan's default) is how long the command may take before the capture fails with `timeout`. Raise it for tools that are slow to start on a cold machine. It must be a finite number above 0 and at most 600; anything else is a usage error (exit status 2).
- The file is written to `--out` (default `versionbar-captures/`) as `<os>-<tool>-<version>.json`, for example `windows-git-2.55.0.windows.2.json`; a provider's listing command as `<os>-<tool>-<provider>-listing.json`, since a listing names many versions. The command prints the destination; with `--json` it prints `{"outcome": "captured", "tool", "destination", "exit_code"}`.
- A command that runs but fails (non-zero exit) is still captured, with its true exit status. That is evidence too.
- Failures write no file, so a failed capture never looks like a fixture. With `--json` the error is `{"outcome", "tool", "message"}`.
  - Exit status 2 (usage error, like `show`): `unknown-tool`; `unknown-source` for a `--source` that is no provider, or a provider that reports no installs of that tool; and `unsupported-os` for a known tool with no definition for this OS (message: `<id> is not available on <os>`) or a provider that does not run on it.
  - Exit status 1: `not-found` (not on `PATH`, or the provider reports no install), `timeout`, `launch-error` (including no exit status, and a `--source` provider that fails to list its installs or name its listing command), `write-failed`.

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

Fixtures live under `core/tests/fixtures/<tool>/`; captures made with `--source` (a provider's listing, or an install it found) under `core/tests/fixtures/<provider>/`. Name them `<os>-<tool>-<version>.json`, or `<os>-<tool>-<provider>-listing.json` for a provider's listing command, which is what the command already produces. Every tool and provider needs a real capture; never write output by hand. A hand-made seed is only acceptable when `provenance.notes` says which machine and command produced it.

## Capture on a clean Windows runner

The `Capture tool output` workflow (`.github/workflows/capture.yml`) is the single shared route for this. It runs on `windows-latest`, is dispatched by hand only, and never installs any tool, so a tool the runner image lacks yields a `not-found` outcome instead of a capture.

```sh
gh workflow run capture.yml -f tools="git node"            # tool ids, space or comma separated
gh workflow run capture.yml -f tools=mytool -f ref=my-branch   # draft definitions from a reviewed branch
gh workflow run capture.yml -f tools=dotnet -f source=dotnet   # a provider's listing (or first install) instead of PATH's
gh workflow run capture.yml -f tools="kubectl choco" -f timeout=30   # slow tools: seconds per command
gh run list --workflow capture.yml --limit 1               # find the run id
gh run watch <run-id>
gh run download <run-id> -n captures-<run-id>
```

GitHub returns 404 when you dispatch a workflow that is not on the default branch, even with `--ref`, so the workflow must be on `main`, and the commands above run `main`'s copy of it: a change to the workflow itself (such as the `source` and `timeout` inputs) is only usable once it has landed on `main`. The `ref` input then chooses which code is checked out and run, so it is how a branch of draft definitions gets captured.

The job stays green whatever the capture outcomes are; read `outcomes/` rather than the job status. Only rejected inputs (no ids, or a malformed id) fail the job.

Tool ids and `source` must match `[a-z0-9][a-z0-9-]*`, and `timeout` must be a plain number of seconds (`30`, `12.5`); anything else is rejected before any command runs. `source` and `timeout` apply to every tool in the run. The artifact `captures-<run-id>` holds:

- `captures/`: one capture file per successful tool.
- `outcomes/<tool>.json`: the command's result for every requested tool, including `not-found`, `unknown-tool` and `timeout` failures.
- `outcomes/provenance.json`: workflow run URL, checked-out commit, requested ref, source, effective timeout in seconds (5 when unset), runner image name and version, and the fixed invocation used.

Copy the files you want into `core/tests/fixtures/<tool>/` (or `<provider>/` for a `source` run) and review them like any other change. `source` only helps for managers the runner image already has, such as the .NET host or the py launcher; the workflow installs nothing, so other managers are captured with `--source` on your own machine.

## Attaching a capture to a bug report

Attach the `.json` file from `debug capture` to the issue. It contains the bytes needed to reproduce the problem plus the OS and resolved path. Your profile folder is already replaced by `%USERPROFILE%`, but an install elsewhere (or a tool that prints its own path) can still reveal names, so skim `provenance.resolved_path` and the `*_text` fields first.
