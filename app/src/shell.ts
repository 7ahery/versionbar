import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useCallback, useEffect, useState } from "react";
import type { ConfigResult, ScanResult } from "schema";

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

export const PREFERENCES_UPDATED = "preferences-updated";

/**
 * What `get_preferences` returns and `preferences-updated` carries (docs/app/preferences.md).
 * `config` is the core's answer as printed, including one for an invalid config
 * (`preferences` null, `problems` says why); null until a query has answered. `outcome` is
 * how the latest query went, in the scan's shape.
 */
export interface PreferencesState {
  config: ConfigResult | null;
  outcome: Outcome | null;
}

export const UPDATE_UPDATED = "update-updated";

/**
 * What `get_update` returns and `update-updated` carries (docs/app/updates.md). Mirrors
 * `UpdateState` in app/src-tauri/src/update.rs. Rust checks the signed feed on its own; the
 * popup only shows the offer and confirms it.
 */
export interface UpdateState {
  /** The newer version on offer; null when there is none or update checks are off. */
  version: string | null;
  /** True from the confirmation until the install fails or the app restarts. */
  installing: boolean;
  /** Why the last confirmed install failed, as a sentence for the user. */
  error: string | null;
}

/**
 * Follows one piece of shell state: takes every `event`, and asks `command` for the current
 * value once the subscription is in place.
 */
// T names the payload both `listen` and `invoke` hand back; each caller states it once.
// eslint-disable-next-line @typescript-eslint/no-unnecessary-type-parameters
function useShellValue<T>(event: string, command: string): T | null {
  const [value, setValue] = useState<T | null>(null);

  useEffect(() => {
    let active = true;
    // Once an event has arrived, the command's answer adds nothing: any change after the
    // event was sent comes as another event. An answer that lands after the event may also
    // have been read before it, so it must not overwrite it.
    let heardEvent = false;
    let unlisten: (() => void) | null = null;
    const follow = async () => {
      try {
        const stop = await listen<T>(event, (heard) => {
          heardEvent = true;
          if (active) setValue(heard.payload);
        });
        if (active) unlisten = stop;
        else stopQuietly(stop);
      } catch {
        // No event bridge (shell gone): the command below is all we can do.
      }
      // Only asked once the shell is sending us events: an event sent while the listener
      // was still being set up reaches nobody, and an earlier answer would then be the
      // last word and could stay stale (say, "scanning") for good.
      try {
        const initial = await invoke<T>(command);
        if (active && !heardEvent) setValue(initial);
      } catch {
        // Without the shell there is nothing to show yet; events may still arrive.
      }
    };
    void follow();
    return () => {
      active = false;
      if (unlisten) stopQuietly(unlisten);
    };
  }, [event, command]);

  return value;
}

/** Follows the preferences the shell read from the core; null until the shell first answers. */
export function usePreferences(): PreferencesState | null {
  return useShellValue<PreferencesState>(
    PREFERENCES_UPDATED,
    "get_preferences",
  );
}

/**
 * Follows the shell's scan state: asks for it once on mount, then takes every
 * `scan-updated` event. `refresh` asks the shell to scan; progress arrives as events.
 */
export function useShellState(): {
  state: ShellState | null;
  refresh: () => void;
} {
  const state = useShellValue<ShellState>(SCAN_UPDATED, "get_state");

  const refresh = useCallback(() => {
    // Failures surface through the state the shell announces, not through this call.
    invoke("refresh").catch(() => {});
  }, []);

  return { state, refresh };
}

/**
 * Follows the update the shell found; null until the shell first answers. `install` is the
 * user's confirmation: the shell installs what it offered and restarts the app.
 */
export function useUpdate(): {
  update: UpdateState | null;
  install: () => void;
} {
  const update = useShellValue<UpdateState>(UPDATE_UPDATED, "get_update");

  const install = useCallback(() => {
    // Failures surface through the state the shell announces, not through this call.
    invoke("install_update").catch(() => {});
  }, []);

  return { update, install };
}

/** Opens the official uv installation guide in the browser; the shell knows the address. */
export function openUvDocs() {
  invoke("open_uv_docs").catch(() => {});
}

/**
 * Shows an install in Explorer with the file selected. Rejects with a sentence for the user
 * when the shell refuses the path or cannot start Explorer.
 */
export async function openContainingFolder(path: string): Promise<void> {
  try {
    await invoke("open_containing_folder", { path });
  } catch (error) {
    // The shell's own errors are strings written for the user; anything else is the bridge.
    throw new Error(
      typeof error === "string" ? error : "Could not open the folder.",
      { cause: error },
    );
  }
}

/** Unsubscribing can fail while the webview is being torn down; nothing is left to do then. */
function stopQuietly(stop: () => void) {
  try {
    stop();
  } catch {
    // Ignored on purpose, see above.
  }
}
