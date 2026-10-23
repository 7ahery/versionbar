# Unsigned installer, signed updater, CI-only releases

The NSIS per-user installer is unsigned in v1 (SHA-256 checksums and a README SmartScreen note; SignPath later), while updater metadata is cryptographically signed with Tauri's updater key held as a CI secret. release-please with Conventional Commits drives a release PR; the tag triggers CI to build the installer, checksums and update metadata and to publish the core to PyPI via Trusted Publishing. Nothing is built locally and there is no telemetry.
