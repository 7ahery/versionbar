import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useCallback, useEffect, useState } from "react";
import type { ScanResult } from "schema";

/**
 * The scan state the Rust shell holds, as `get_state` returns it and `scan-updated` carries
 * it. Mirrors `ShellState` in app/src-tauri/src/scan.rs. `current` and `previous` are exactly
 * what the core printed: Rust only checked `schema_version`, so everything else is ours to
 * interpret, ignoring unknown fields and handling unknown enum values.
 */
export interface ShellState {
  scanning: boolean;
  current: ScanResult | null;
  previous: ScanResult | null;
  /** How the latest finished attempt went; null until one finishes. */
  outcome: Outcome | null;
}

/**
 * `kind` is `ok`, `uv_missing` or `failed` (which adds the other fields). New kinds and
 * reasons may appear (ticket 22 adds a setup state), so this stays loose and callers keep a
 * default branch.
 */
export interface Outcome {
  kind: string;
  /** `launch`, `timeout`, `exit`, `malformed` or `incompatible`. */
  reason?: string;
  /** One line for the user. */
  message?: string;
  stderr?: string;
}

export const SCAN_UPDATED = "scan-updated";

/**
 * Follows the shell's scan state: asks for it once on mount, then takes every
 * `scan-updated` event. `refresh` asks the shell to scan; progress arrives as events.
 */
export function useShellState(): {
  state: ShellState | null;
  refresh: () => void;
} {
  const [state, setState] = useState<ShellState | null>(null);

  useEffect(() => {
    let active = true;
    // An event is always newer than the get_state answer, which may have been read before
    // the event was sent, so a late answer must not overwrite it.
    let heardEvent = false;
    let unlisten: (() => void) | null = null;
    listen<ShellState>(SCAN_UPDATED, (event) => {
      heardEvent = true;
      if (active) setState(event.payload);
    }).then(
      (stop) => {
        if (active) unlisten = stop;
        else stopQuietly(stop);
      },
      // No event bridge (shell gone): get_state below is all we can do.
      () => {},
    );
    invoke<ShellState>("get_state").then(
      (initial) => {
        if (active && !heardEvent) setState(initial);
      },
      // Without the shell there is nothing to show yet; events may still arrive.
      () => {},
    );
    return () => {
      active = false;
      if (unlisten) stopQuietly(unlisten);
    };
  }, []);

  const refresh = useCallback(() => {
    // Failures surface through the state the shell announces, not through this call.
    invoke("refresh").catch(() => {});
  }, []);

  return { state, refresh };
}

/** Unsubscribing can fail while the webview is being torn down; nothing is left to do then. */
function stopQuietly(stop: () => void) {
  try {
    stop();
  } catch {
    // Ignored on purpose, see above.
  }
}
