import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { emit } from "@tauri-apps/api/event";
import { mockIPC } from "@tauri-apps/api/mocks";
import type { ScanResult } from "schema";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { ShellState } from "./shell";
import realScan from "./test/fixtures/list-windows.json";

/** Real `versionbar list --json` output (profile path redacted), as the shell passes it on. */
const scan = realScan as ScanResult;
const SCANNED_AT = Date.parse(scan.scanned_at);

function state(overrides: Partial<ShellState> = {}): ShellState {
  return {
    scanning: false,
    current: scan,
    previous: null,
    outcome: { kind: "ok" },
    ...overrides,
  };
}

/** Answers the shell's commands the way Rust does and records what was called. */
function shell(initial: ShellState) {
  const calls: string[] = [];
  mockIPC(
    (cmd) => {
      calls.push(cmd);
      if (cmd === "plugin:app|version") return "0.1.0";
      if (cmd === "get_state") return initial;
      if (cmd === "refresh") return null;
      throw new Error(`unexpected command ${cmd}`);
    },
    { shouldMockEvents: true },
  );
  return calls;
}

/** The popup's tool rows, keyed by tool name. */
function row(name: string): HTMLElement {
  const item = screen.getByText(name).closest("li");
  if (!item) throw new Error(`no row for ${name}`);
  return item;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("popup", () => {
  it("shows the product name and the version the shell reports", async () => {
    shell(state());

    render(<App />);

    expect(screen.getByRole("heading", { name: "VersionBar" })).toBeDefined();
    expect(await screen.findByText("v0.1.0")).toBeDefined();
  });

  it("still renders when the shell cannot answer", async () => {
    let asked = false;
    mockIPC(() => {
      asked = true;
      throw new Error("ipc unavailable");
    });

    render(<App />);
    await waitFor(() => {
      expect(asked).toBe(true);
    });

    expect(screen.getByRole("heading", { name: "VersionBar" })).toBeDefined();
    expect(screen.queryByText(/^v\d/)).toBeNull();
  });

  it("lists each tool with its active version from a real scan", async () => {
    shell(state());

    render(<App />);

    await screen.findByText("Git");
    expect(within(row("Git")).getByText("2.55.0.windows.2")).toBeDefined();
    expect(within(row("Node.js")).getByText("24.21.0")).toBeDefined();
    expect(within(row("uv")).getByText("0.12.23")).toBeDefined();
    expect(within(row("Python")).getByText("Not found")).toBeDefined();
  });

  it("says how long ago the shown scan ran", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(SCANNED_AT + 3 * 60_000);
    shell(state());

    render(<App />);

    expect(await screen.findByText("Scanned 3 min ago")).toBeDefined();
  });

  it("shows that the first scan is running before there is any data", async () => {
    shell(state({ scanning: true, current: null, outcome: null }));

    render(<App />);

    expect(await screen.findByText("Scanning…")).toBeDefined();
    expect(
      screen.getByRole("button", { name: "Refresh" }).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("asks the shell to scan when Refresh is pressed", async () => {
    const calls = shell(state());
    render(<App />);
    await screen.findByText("Git");

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => {
      expect(calls).toContain("refresh");
    });
  });

  it("follows scan-updated events from the shell", async () => {
    shell(state({ scanning: true, current: null, outcome: null }));
    render(<App />);
    await screen.findByText("Scanning…");

    await act(() => emit("scan-updated", state()));

    expect(await screen.findByText("Git")).toBeDefined();
    expect(screen.queryByText("Scanning…")).toBeNull();
  });

  it("is not left on a stale state when a scan ends while it subscribes", async () => {
    // Models the real shell: a listener counts only once the shell has handled the listen
    // request, and an event sent before that reaches nobody.
    let current = state({ scanning: true, current: null, outcome: null });
    const handlers: number[] = [];
    let finishSubscribing: (() => void) | null = null;
    mockIPC((cmd, args) => {
      if (cmd === "plugin:app|version") return "0.1.0";
      if (cmd === "get_state") return current;
      if (cmd === "plugin:event|listen") {
        const { handler } = args as { handler: number };
        return new Promise((resolve) => {
          finishSubscribing = () => {
            handlers.push(handler);
            resolve(handler);
          };
        });
      }
      if (cmd === "plugin:event|unlisten") return null;
      throw new Error(`unexpected command ${cmd}`);
    });
    // mockIPC installs this bridge; it is how Tauri delivers events to the page.
    const bridge = (
      window as unknown as {
        __TAURI_INTERNALS__: {
          runCallback: (id: number, data: unknown) => void;
        };
      }
    ).__TAURI_INTERNALS__;
    const announce = (next: ShellState) => {
      current = next;
      for (const handler of handlers) {
        bridge.runCallback(handler, {
          event: "scan-updated",
          id: handler,
          payload: next,
        });
      }
    };

    render(<App />);
    await waitFor(() => {
      expect(finishSubscribing).not.toBeNull();
    });
    announce(state());
    act(() => {
      finishSubscribing?.();
    });

    expect(await screen.findByText("Git")).toBeDefined();
    expect(screen.queryByText("Scanning…")).toBeNull();
  });

  it("keeps showing the last results while a refresh runs", async () => {
    shell(state());
    render(<App />);
    await screen.findByText("Git");

    await act(() => emit("scan-updated", state({ scanning: true })));

    expect(screen.getByText("Scanning…")).toBeDefined();
    expect(within(row("Git")).getByText("2.55.0.windows.2")).toBeDefined();
  });

  it("opens on the saved results and their age while the launch scan runs", async () => {
    // After a restart the shell has restored yesterday's results but nothing has finished
    // yet; with core-env gone that first scan is even a one-time setup.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(SCANNED_AT + 26 * 60 * 60_000);
    shell(state({ scanning: true, setting_up: true, outcome: null }));

    render(<App />);

    expect(await screen.findByText("Scanned 1 d ago")).toBeDefined();
    expect(screen.getByText("Scanning…")).toBeDefined();
    expect(within(row("Git")).getByText("2.55.0.windows.2")).toBeDefined();
    expect(screen.queryByText(/One-time setup/)).toBeNull();
  });

  it("keeps the age of the shown results next to a failure", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(SCANNED_AT + 45 * 60_000);
    shell(
      state({
        outcome: {
          kind: "failed",
          reason: "exit",
          message: "The scan failed (code 3).",
          stderr: "",
        },
      }),
    );

    render(<App />);

    expect(await screen.findByText("The scan failed (code 3).")).toBeDefined();
    expect(screen.getByText("Scanned 45 min ago")).toBeDefined();
  });

  it("reports a failed scan without dropping the last results", async () => {
    shell(
      state({
        outcome: {
          kind: "failed",
          reason: "timeout",
          message: "The scan did not finish within 30 seconds.",
          stderr: "",
        },
      }),
    );

    render(<App />);

    expect(
      await screen.findByText("The scan did not finish within 30 seconds."),
    ).toBeDefined();
    expect(within(row("Git")).getByText("2.55.0.windows.2")).toBeDefined();
  });

  it("says when uv cannot be found", async () => {
    shell(state({ current: null, outcome: { kind: "uv_missing" } }));

    render(<App />);

    expect(await screen.findByText(/uv was not found/)).toBeDefined();
  });

  it("copes with fields and values this version does not know", async () => {
    const future = structuredClone(scan) as ScanResult & {
      added_later: unknown;
    };
    future.added_later = { nested: true };
    const git = future.tools[0];
    if (!git) throw new Error("fixture has no tools");
    git.status = "quarantined" as ScanResult["tools"][number]["status"];
    git.active = null;
    shell(state({ current: future, outcome: { kind: "setting_up" } }));

    render(<App />);

    expect(await screen.findByText("quarantined")).toBeDefined();
    expect(within(row("Node.js")).getByText("24.21.0")).toBeDefined();
  });
});
