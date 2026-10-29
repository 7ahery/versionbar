import { act, fireEvent, render, screen } from "@testing-library/react";
import { emit } from "@tauri-apps/api/event";
import { mockIPC } from "@tauri-apps/api/mocks";
import type { ScanResult } from "schema";
import { describe, expect, it } from "vitest";

import App from "./App";
import type { ShellState, UpdateState } from "./shell";
import realScan from "./test/fixtures/list-windows.json";

const scan: ShellState = {
  scanning: false,
  current: realScan as ScanResult,
  previous: null,
  outcome: { kind: "ok" },
};

const NONE: UpdateState = { version: null, installing: false, error: null };

function offer(overrides: Partial<UpdateState> = {}): UpdateState {
  return { version: "0.2.0", installing: false, error: null, ...overrides };
}

/** Answers the shell's commands the way Rust does and records what was called. */
function shell(update: UpdateState) {
  const calls: string[] = [];
  mockIPC(
    (cmd) => {
      calls.push(cmd);
      if (cmd === "plugin:app|version") return "0.1.0";
      if (cmd === "get_state") return scan;
      if (cmd === "get_update") return update;
      if (cmd === "install_update") return null;
      throw new Error(`unexpected command ${cmd}`);
    },
    { shouldMockEvents: true },
  );
  return calls;
}

const BANNER = "Update to v0.2.0 → Install & restart";

describe("update banner", () => {
  it("is absent while no update is offered", async () => {
    shell(NONE);
    render(<App />);
    expect(await screen.findByText("Git")).toBeDefined();
    expect(
      screen.queryByRole("button", { name: /Install & restart/ }),
    ).toBeNull();
  });

  it("offers the version the shell found, alongside the tool list", async () => {
    shell(offer());
    render(<App />);
    expect(await screen.findByRole("button", { name: BANNER })).toBeDefined();
    expect(screen.getByText("Git")).toBeDefined();
  });

  it("appears when the shell announces an update after a check", async () => {
    shell(NONE);
    render(<App />);
    expect(await screen.findByText("Git")).toBeDefined();
    await act(async () => {
      await emit("update-updated", offer());
    });
    expect(screen.getByRole("button", { name: BANNER })).toBeDefined();
  });

  it("installs only when confirmed, asking the shell once", async () => {
    const calls = shell(offer());
    render(<App />);
    const button = await screen.findByRole("button", { name: BANNER });
    expect(calls).not.toContain("install_update");

    fireEvent.click(button);
    fireEvent.click(button);

    expect(calls.filter((cmd) => cmd === "install_update")).toHaveLength(1);
  });

  it("shows the install in progress", async () => {
    shell(offer({ installing: true }));
    render(<App />);
    expect(await screen.findByText("Installing v0.2.0…")).toBeDefined();
    expect(screen.queryByRole("button", { name: BANNER })).toBeNull();
  });

  it("shows why a confirmed install failed, keeps the list and offers Retry", async () => {
    const message =
      "The update could not be installed: the signature does not match.";
    const calls = shell(offer());
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: BANNER }));
    await act(async () => {
      await emit("update-updated", offer({ installing: true }));
    });
    await act(async () => {
      await emit("update-updated", offer({ error: message }));
    });

    expect(screen.getByText(message)).toBeDefined();
    expect(screen.getByText("Git")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Retry update" }));
    expect(calls.filter((cmd) => cmd === "install_update")).toHaveLength(2);
  });
});
