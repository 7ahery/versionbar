import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { emit } from "@tauri-apps/api/event";
import { mockIPC } from "@tauri-apps/api/mocks";
import type { ScanResult } from "schema";
import { afterEach, describe, expect, it } from "vitest";

import App from "./App";
import type { ShellState } from "./shell";
import realScan from "./test/fixtures/list-windows.json";

const scan = realScan as ScanResult;

/** A popup with no results yet, as on a first run or after a failed one. */
function empty(overrides: Partial<ShellState> = {}): ShellState {
  return {
    scanning: false,
    setting_up: false,
    current: null,
    previous: null,
    outcome: null,
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
      if (cmd === "refresh" || cmd === "open_uv_docs") return null;
      throw new Error(`unexpected command ${cmd}`);
    },
    { shouldMockEvents: true },
  );
  return calls;
}

/** Replaces the clipboard; `fail` makes every copy be refused. */
function clipboard(fail = false) {
  const copied: string[] = [];
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: (text: string) => {
        if (fail) return Promise.reject(new Error("denied"));
        copied.push(text);
        return Promise.resolve();
      },
    },
  });
  return copied;
}

const missingUv = empty({ outcome: { kind: "uv_missing" } });

function failure(stderr: string, reason = "exit"): ShellState {
  return empty({
    outcome: {
      kind: "failed",
      reason,
      message: "The scan failed (code 2).",
      stderr,
    },
  });
}

afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("preparing the environment", () => {
  it("explains the first run and what uv may download", async () => {
    shell(empty({ scanning: true, setting_up: true }));

    render(<App />);

    expect(
      await screen.findByText("One-time setup: preparing Python environment…"),
    ).toBeDefined();
    expect(screen.getByText(/uv may download and install/)).toBeDefined();
    expect(
      screen.getByText(/VersionBar never installs or changes your tools/),
    ).toBeDefined();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("gives way to the list when the first scan succeeds", async () => {
    shell(empty({ scanning: true, setting_up: true }));
    render(<App />);
    await screen.findByText("One-time setup: preparing Python environment…");

    await act(() =>
      emit("scan-updated", empty({ current: scan, outcome: { kind: "ok" } })),
    );

    expect(await screen.findByText("Git")).toBeDefined();
    expect(
      screen.queryByText("One-time setup: preparing Python environment…"),
    ).toBeNull();
  });

  it("is not shown for an ordinary scan", async () => {
    shell(empty({ scanning: true }));

    render(<App />);

    await screen.findByText("Scanning…");
    expect(
      screen.queryByText("One-time setup: preparing Python environment…"),
    ).toBeNull();
  });
});

describe("uv is missing while earlier results exist", () => {
  const withResults = empty({ current: scan, outcome: { kind: "uv_missing" } });

  it("keeps the list and still offers the command, docs link and Retry", async () => {
    const copied = clipboard();
    const calls = shell(withResults);

    render(<App />);

    expect(await screen.findByText("Git")).toBeDefined();
    expect(screen.getByText("winget install astral-sh.uv")).toBeDefined();
    expect(
      screen.getByRole("button", { name: "Open the uv install guide" }),
    ).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Copy command" }));
    expect(await screen.findByText("Copied")).toBeDefined();
    expect(copied).toEqual(["winget install astral-sh.uv"]);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(calls).toContain("refresh");
    });
  });
});

describe("uv is missing", () => {
  it("shows the winget command, the docs link and says nothing is installed for you", async () => {
    shell(missingUv);

    render(<App />);

    expect(await screen.findByText("uv was not found")).toBeDefined();
    expect(screen.getByText("winget install astral-sh.uv")).toBeDefined();
    expect(screen.getByText(/does not install uv/)).toBeDefined();
    // The running app keeps the PATH it started with, so restarting is the expected step.
    expect(screen.getByText(/quit and restart VersionBar/)).toBeDefined();
    expect(
      screen.getByRole("button", { name: "Open the uv install guide" }),
    ).toBeDefined();
  });

  it("copies the command", async () => {
    const copied = clipboard();
    shell(missingUv);
    render(<App />);
    await screen.findByText("uv was not found");

    fireEvent.click(screen.getByRole("button", { name: "Copy command" }));

    expect(await screen.findByText("Copied")).toBeDefined();
    expect(copied).toEqual(["winget install astral-sh.uv"]);
  });

  it("says so when the clipboard refuses, leaving the command to select", async () => {
    clipboard(true);
    shell(missingUv);
    render(<App />);
    await screen.findByText("uv was not found");

    fireEvent.click(screen.getByRole("button", { name: "Copy command" }));

    expect(await screen.findByText(/Could not copy/)).toBeDefined();
    expect(screen.getByText("winget install astral-sh.uv")).toBeDefined();
  });

  it("opens the install guide through the shell", async () => {
    const calls = shell(missingUv);
    render(<App />);
    await screen.findByText("uv was not found");

    fireEvent.click(
      screen.getByRole("button", { name: "Open the uv install guide" }),
    );

    await waitFor(() => {
      expect(calls).toContain("open_uv_docs");
    });
  });

  it("scans again on Retry and leaves the screen once uv works", async () => {
    const calls = shell(missingUv);
    render(<App />);
    await screen.findByText("uv was not found");

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(calls).toContain("refresh");
    });
    await act(() =>
      emit("scan-updated", empty({ current: scan, outcome: { kind: "ok" } })),
    );

    expect(await screen.findByText("Git")).toBeDefined();
    expect(screen.queryByText("uv was not found")).toBeNull();
  });

  it("disables Retry while a scan runs", async () => {
    shell(empty({ scanning: true, outcome: { kind: "uv_missing" } }));

    render(<App />);

    const retry = await screen.findByRole("button", { name: /Retry/ });
    expect(retry.hasAttribute("disabled")).toBe(true);
  });
});

describe("the scan failed", () => {
  it("shows the message and only the last lines of stderr", async () => {
    const lines = Array.from({ length: 30 }, (_, i) => `line ${String(i + 1)}`);
    shell(failure(lines.join("\n")));

    render(<App />);

    expect(await screen.findByText("The scan failed (code 2).")).toBeDefined();
    expect(screen.getByLabelText("Error output").textContent).toBe(
      lines.slice(-12).join("\n"),
    );
  });

  it("copies the whole error, not only the lines shown", async () => {
    const copied = clipboard();
    const lines = Array.from({ length: 30 }, (_, i) => `line ${String(i + 1)}`);
    shell(failure(lines.join("\n")));
    render(<App />);
    await screen.findByText("The scan failed (code 2).");

    fireEvent.click(screen.getByRole("button", { name: "Copy error" }));

    expect(await screen.findByText("Copied")).toBeDefined();
    expect(copied).toEqual([
      `The scan failed (code 2).\n\n${lines.join("\n")}`,
    ]);
  });

  it("retries through the shell", async () => {
    const calls = shell(failure("error: network unreachable"));
    render(<App />);
    await screen.findByText(/network unreachable/);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(calls).toContain("refresh");
    });
  });

  it("copes with a failure that printed nothing", async () => {
    shell(failure("", "timeout"));

    render(<App />);

    expect(await screen.findByText("The scan failed (code 2).")).toBeDefined();
    expect(screen.queryByLabelText("Error output")).toBeNull();
    expect(screen.getByRole("button", { name: "Retry" })).toBeDefined();
  });

  it.each(["exit", "timeout"])(
    "mentions uv's own downloads for a %s failure",
    async (reason) => {
      shell(failure("error: download failed", reason));

      render(<App />);

      expect(
        await screen.findByText(/uv may download and install/),
      ).toBeDefined();
      expect(
        screen.getByText(/VersionBar never installs or changes your tools/),
      ).toBeDefined();
    },
  );

  it.each(["launch", "malformed", "incompatible"])(
    "does not mention downloads for a %s failure",
    async (reason) => {
      shell(failure("something else", reason));

      render(<App />);

      await screen.findByText("The scan failed (code 2).");
      expect(screen.queryByText(/uv may download/)).toBeNull();
    },
  );
});

describe("unknown outcomes", () => {
  it("fall back to the plain empty state", async () => {
    shell(empty({ outcome: { kind: "something_new" } }));

    render(<App />);

    expect(await screen.findByText("No scan results yet.")).toBeDefined();
  });
});
