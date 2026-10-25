import { act, renderHook, waitFor } from "@testing-library/react";
import { emit } from "@tauri-apps/api/event";
import { mockIPC } from "@tauri-apps/api/mocks";
import type { ConfigResult } from "schema";
import { describe, expect, it } from "vitest";

import { type PreferencesState, usePreferences } from "./shell";
import defaults from "./test/fixtures/config-windows-defaults.json";
import invalid from "./test/fixtures/config-windows-invalid.json";
import updateOff from "./test/fixtures/config-windows-update-off.json";

/** Real `versionbar config --json` output, as the shell passes it on. */
function answer(config: unknown): PreferencesState {
  return { config: config as ConfigResult, outcome: { kind: "ok" } };
}

function shell(initial: PreferencesState) {
  mockIPC(
    (cmd) => {
      if (cmd === "get_preferences") return initial;
      throw new Error(`unexpected command ${cmd}`);
    },
    { shouldMockEvents: true },
  );
}

describe("usePreferences", () => {
  it("is null until the shell answers, then gives the default preferences", async () => {
    shell(answer(defaults));
    const { result } = renderHook(() => usePreferences());
    expect(result.current).toBeNull();
    await waitFor(() => {
      expect(result.current?.config?.preferences).toEqual(defaults.preferences);
    });
    expect(result.current?.outcome).toEqual({ kind: "ok" });
  });

  it("follows a preferences-updated event after a config change", async () => {
    shell(answer(defaults));
    const { result } = renderHook(() => usePreferences());
    await waitFor(() => {
      expect(result.current?.config?.preferences?.update_check).toBe(true);
    });
    await act(async () => {
      await emit("preferences-updated", answer(updateOff));
    });
    expect(result.current?.config?.preferences?.update_check).toBe(false);
  });

  it("exposes the problems of an invalid config, which has no preferences", async () => {
    shell(answer(invalid));
    const { result } = renderHook(() => usePreferences());
    await waitFor(() => {
      expect(result.current?.config?.problems).toEqual([
        {
          key: "app.update_check",
          message: "Input should be a valid boolean",
        },
      ]);
    });
    expect(result.current?.config?.preferences).toBeNull();
    expect(result.current?.config?.config_path).toContain("config.toml");
  });

  it("keeps an event's answer over a get_preferences answer that lands later", async () => {
    const late: { release?: (value: PreferencesState) => void } = {};
    mockIPC(
      (cmd) => {
        if (cmd === "get_preferences")
          return new Promise<PreferencesState>((resolve) => {
            late.release = resolve;
          });
        throw new Error(`unexpected command ${cmd}`);
      },
      { shouldMockEvents: true },
    );
    const { result } = renderHook(() => usePreferences());
    await waitFor(() => {
      expect(late.release).toBeDefined();
    });
    await act(async () => {
      await emit("preferences-updated", answer(updateOff));
    });
    // Async so the hook's `await invoke` continuation runs inside the act.
    await act(async () => {
      late.release?.(answer(defaults));
    });
    expect(result.current?.config?.preferences?.update_check).toBe(false);
  });
});
