# The core scans live; only the Rust shell keeps state

The core and CLI never cache, so scripts and agents never act on stale data. The tray app needs instant popups, so the Rust shell stores the current and previous results on disk, refreshes on an interval (30 min default) and emits scan-updated events. Caching in the core was rejected because it would make `check` unreliable.
