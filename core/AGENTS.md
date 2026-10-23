# Core (Python) agent guide

Applies to everything under `core/`. Root rules in `../AGENTS.md` also apply.

- Python 3.14+, run through uv only. Tooling: ruff (lint and format), ty (types).
- **Hybrid definitions.** Simple tools are declarative TOML definitions (name, binaries, version args, version regex, optional per-OS overrides) with no engine code. Version managers are Python provider classes that declare the tools they serve and the OSes they support. Do not add per-tool branches to the engine.
- **One system interface.** Process execution with timeout, PATH and environment reads, executable resolution, file existence and directory listing all go through it. The real implementation sits behind the platform boundary; tests inject a fixture-backed fake. Keep OS-specific code behind that boundary.
- **Detection rules:** follow PATHEXT; report Microsoft Store `python.exe`/`python3.exe` placeholders as missing with a note; tag shim-served installs with `via`; detect output encoding per tool (UTF-16 for WSL); de-duplicate PATH entries; find managers through environment variables (e.g. `NVM_HOME`), not fixed paths.
- **No caching.** Scan live, in parallel on a thread pool, with a per-command timeout (5 s default) that yields status `timeout`.
- **CLI:** Typer plus Rich. Rich is for human output only; `--json` works on every command and must never import Rich or emit colour or decoration.
- **JSON contract:** Pydantic models are the source of truth. Regenerate the committed schema and TS types with `npm run gen`.
- **Tests:** drive the CLI entry point over the fake system. Every tool and provider needs a captured fixture from `versionbar debug capture`. Until that command exists (ticket 05), a hand-seeded real capture is acceptable if attributable (machine and command recorded beside it); never invent output.
- The CLI never installs, upgrades or switches anything.
