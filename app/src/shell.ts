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
  /** The running scan is the first one, which sets up the core's environment. */
  setting_up?: boolean;
  current: ScanResult | null;
  previous: ScanResult | null;
  /** How the latest finished attempt went; null until one finishes. */
  outcome: Outcome | null;
}

/**
 * `kind` is `ok`, `uv_missing` or `failed` (which adds the other fields). New kinds and
 * reasons may appear, so this stays loose and callers keep a default branch.
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
    // Once an event has arrived, the get_state answer adds nothing: any change after the
    // event was sent comes as another event. An answer that lands after the event may also
    // have been read before it, so it must not overwrite it.
    let heardEvent = false;
    let unlisten: (() => void) | null = null;
    const follow = async () => {
      try {
        const stop = await listen<ShellState>(SCAN_UPDATED, (event) => {
          heardEvent = true;
          if (active) setState(event.payload);
        });
        if (active) unlisten = stop;
        else stopQuietly(stop);
      } catch {
        // No event bridge (shell gone): get_state below is all we can do.
      }
      // Only asked once the shell is sending us events: an event sent while the listener
      // was still being set up reaches nobody, and an earlier answer would then be the
      // last word and could stay stale (say, "scanning") for good.
      try {
        const initial = await invoke<ShellState>("get_state");
        if (active && !heardEvent) setState(initial);
      } catch {
        // Without the shell there is nothing to show yet; events may still arrive.
      }
    };
    void follow();
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

/** Opens the official uv installation guide in the browser; the shell knows the address. */
export function openUvDocs() {
  invoke("open_uv_docs").catch(() => {});
}

/** Unsubscribing can fail while the webview is being torn down; nothing is left to do then. */
function stopQuietly(stop: () => void) {
  try {
    stop();
  } catch {
    // Ignored on purpose, see above.
  }
}
