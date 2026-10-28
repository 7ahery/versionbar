# Python core, supported only through uv

The core is Python 3.14+ and is the product: a CLI also published to PyPI. uv is a hard requirement (bundled app, `uv tool install`, `uvx`), so the core always runs on a uv-managed Python and never depends on the system Python it reports on, which on Windows is often a Store placeholder. Plain pip and pipx on older Pythons are not supported.
