# PyPI install evidence

Filled in by the maintainer after two prereleases are published (for example `0.1.0rc1` and `0.1.0rc2`, made with `Release-As:` footers as in [app/install-proof.md](app/install-proof.md)). Nothing below has been recorded yet. The automated half runs in every release: `verify-dist` installs the built wheel and sdist outside the checkout on Windows and Ubuntu before publishing.

## Procedure

From a folder outside the checkout, with no `versionbar` installed:

```sh
uv --version
uv tool install versionbar==<rc1>
versionbar --version                  # expect <rc1>
uvx versionbar@<rc1> --version        # expect <rc1>
uv tool upgrade versionbar --prerelease allow
versionbar --version                  # expect <rc2>
uv tool list --show-paths             # shows the tool's environment folder
```

Then read the tool environment's `pyvenv.cfg` (`home =` line) or run `uv python list --only-installed`: the interpreter must be a uv-managed one, not a system Python.

## Record

| Date | uv version | Command | Output | Interpreter path (uv-managed?) |
|---|---|---|---|---|
| | | | | |
