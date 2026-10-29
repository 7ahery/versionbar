# PyPI install evidence

Filled in by the maintainer after two prereleases are published (for example `0.1.0rc1` and `0.1.0rc2`, made with `Release-As:` footers as in [app/install-proof.md](app/install-proof.md)). Nothing below has been recorded yet. The automated half runs in every release: `verify-dist` installs the built wheel and sdist outside the checkout on Windows and Ubuntu before publishing.

## Procedure

From a folder outside the checkout, with no `versionbar` installed:

```sh
uv --version
uv tool install "versionbar>=<rc1>" --prerelease allow   # run while <rc1> is the newest published version
versionbar --version                  # expect <rc1>
uvx --from "versionbar==<rc1>" versionbar --version   # expect <rc1>
# publish <rc2>, then:
uv tool upgrade versionbar --prerelease allow
versionbar --version                  # expect <rc2>
uv tool list --show-paths             # shows the tool's environment folder
```

Do not install with `versionbar==<rc1>`: uv keeps an exact pin and `uv tool upgrade` then reports "Nothing to upgrade". The sequence above was checked with uv 0.12.23 against two real PyPI prereleases (`pytest` 8.0.0rc1 then 8.0.0rc2, with `--exclude-newer` standing in for the time between the two publications, temporary `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR` outside the checkout): the floor install gave `pytest 8.0.0rc1`, `uv tool upgrade pytest --prerelease allow` gave `pytest 8.0.0rc2`, while the exact-pin install printed "Nothing to upgrade ... pinned to `8.0.0rc1` (installed with an exact version pin)". Recorded rows below are the maintainer's own run of `versionbar`.

Then read the tool environment's `pyvenv.cfg` (`home =` line) or run `uv python list --only-installed`: the interpreter must be a uv-managed one, not a system Python.

## Record

| Date | uv version | Command | Output | Interpreter path (uv-managed?) |
|---|---|---|---|---|
| | | | | |
