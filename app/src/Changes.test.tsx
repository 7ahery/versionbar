import { act, fireEvent, render, screen } from "@testing-library/react";
import { emit } from "@tauri-apps/api/event";
import { mockIPC } from "@tauri-apps/api/mocks";
import type { ConfigResult, ScanResult } from "schema";
import { afterEach, describe, expect, it } from "vitest";

import App from "./App";
import type { PreferencesState, ShellState } from "./shell";
import defaultsConfig from "./test/fixtures/config-windows-defaults.json";
import installsScan from "./test/fixtures/list-windows-installs.json";

/**
 * Change highlighting and ordering, driven through the shell's state and preferences like
 * the running app. The base scan is real `list --json` output (Git, Node.js and uv found,
 * Python missing); "previous" scans are that output with a tool edited, which is all a
 * second scan on the same machine would differ by.
 */
const base = installsScan as ScanResult;
type Tool = ScanResult["tools"][number];

function edit(
  scan: ScanResult,
  id: string,
  patch: (tool: Tool) => Partial<Tool>,
): ScanResult {
  return {
    ...scan,
    tools: scan.tools.map((tool) =>
      tool.id === id ? { ...tool, ...patch(tool) } : tool,
    ),
  };
}

function withVersion(scan: ScanResult, id: string, version: string) {
  return edit(scan, id, (tool) => ({
    active: tool.active && { ...tool.active, version },
  }));
}

function without(scan: ScanResult, id: string): ScanResult {
  return { ...scan, tools: scan.tools.filter((tool) => tool.id !== id) };
}

function gone(scan: ScanResult, id: string): ScanResult {
  return edit(scan, id, () => ({
    status: "missing",
    active: null,
    installs: [],
    notes: [],
  }));
}

function failing(scan: ScanResult, id: string): ScanResult {
  return edit(scan, id, () => ({
    status: "error",
    active: null,
    installs: [],
    notes: ["exited with code 1"],
  }));
}

function state(current: ScanResult, previous: ScanResult | null): ShellState {
  return { scanning: false, current, previous, outcome: { kind: "ok" } };
}

function prefs(pinned: string[], order: string[]): PreferencesState {
  const config = {
    ...defaultsConfig,
    preferences: { update_check: true, pinned, order },
  } as ConfigResult;
  return { config, outcome: { kind: "ok" } };
}

function shell(
  initial: ShellState,
  preferences: PreferencesState = prefs([], []),
) {
  mockIPC(
    (cmd) => {
      if (cmd === "plugin:app|version") return "0.1.0";
      if (cmd === "get_state") return initial;
      if (cmd === "get_preferences") return preferences;
      throw new Error(`unexpected command ${cmd}`);
    },
    { shouldMockEvents: true },
  );
}

function namesIn(label: string): (string | null)[] {
  const list = screen.queryByRole("list", { name: label });
  if (!list) return [];
  return Array.from(list.querySelectorAll("[data-tool-name]")).map(
    (node) => node.textContent,
  );
}

const listed = () => namesIn("Tools");

function rowText(name: string): string {
  return (
    screen.getByText(name, { selector: "[data-tool-name]" }).closest("li")
      ?.textContent ?? ""
  );
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("change highlighting", () => {
  it("shows no highlighting and the plain order when there is no previous scan", async () => {
    shell(state(base, null));
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["Git", "Node.js", "uv"]);
    expect(document.body.textContent).not.toContain("→");
    expect(document.body.textContent).not.toMatch(/Newly|Recovered/);
  });

  it("shows an active version change as old → new and lists the changed tool first", async () => {
    shell(state(base, withVersion(base, "node", "20.11.0")));
    render(<App />);
    await screen.findByText("Git");
    expect(rowText("Node.js")).toContain("20.11.0 → 24.21.0");
    expect(rowText("Git")).not.toContain("→");
    expect(listed()).toEqual(["Node.js", "Git", "uv"]);
  });

  it("does not highlight a tool whose active version is the same", async () => {
    shell(state(base, base));
    render(<App />);
    await screen.findByText("Git");
    expect(document.body.textContent).not.toContain("→");
    expect(listed()).toEqual(["Git", "Node.js", "uv"]);
  });

  it("calls a tool absent from the previous scan newly found", async () => {
    shell(state(base, without(base, "uv")));
    render(<App />);
    await screen.findByText("Git");
    expect(rowText("uv")).toContain("Newly found");
    expect(rowText("uv")).toContain("0.12.23");
    expect(listed()[0]).toBe("uv");
  });

  it("calls a tool that was missing and is now found newly found", async () => {
    shell(state(base, gone(base, "uv")));
    render(<App />);
    await screen.findByText("Git");
    expect(rowText("uv")).toContain("Newly found");
  });

  it("calls a tool that was found and is now missing newly missing, in the missing section", async () => {
    shell(state(gone(base, "git"), base));
    render(<App />);
    await screen.findByText("Node.js");
    expect(listed()).toEqual(["Node.js", "uv"]);
    fireEvent.click(screen.getByRole("button", { name: /Show not found/ }));
    // Changed first within the section, ahead of Python which was missing before too.
    expect(namesIn("Not found")).toEqual(["Git", "Python"]);
    expect(rowText("Git")).toContain("Newly missing (was 2.56.0.windows.3)");
    expect(rowText("Python")).not.toContain("Newly");
  });

  it("calls a tool that was found and now errors newly failing, keeping it in the main list", async () => {
    shell(state(failing(base, "git"), base));
    render(<App />);
    await screen.findByText("Node.js");
    expect(listed()[0]).toBe("Git");
    expect(rowText("Git")).toContain("Error");
    expect(rowText("Git")).toContain("Newly failing (was 2.56.0.windows.3)");
  });

  it("does not highlight a tool that errored before and still errors", async () => {
    shell(state(failing(base, "git"), failing(base, "git")));
    render(<App />);
    await screen.findByText("Node.js");
    expect(rowText("Git")).not.toContain("Newly");
    expect(listed()).toEqual(["Git", "Node.js", "uv"]);
  });

  it("calls a tool that errored and is now found recovered, not upgraded and with no earlier version", async () => {
    shell(state(base, failing(base, "node")));
    render(<App />);
    await screen.findByText("Git");
    const text = rowText("Node.js");
    expect(text).toContain("Recovered");
    expect(text).toContain("24.21.0");
    expect(text).not.toContain("→");
    expect(text).not.toMatch(/upgrad/i);
    expect(listed()[0]).toBe("Node.js");
  });

  it("restores highlighting from a saved pair at launch and follows scan-updated", async () => {
    shell(state(base, withVersion(base, "node", "20.11.0")));
    render(<App />);
    await screen.findByText("Git");
    expect(rowText("Node.js")).toContain("20.11.0 → 24.21.0");

    await act(() =>
      emit("scan-updated", state(withVersion(base, "uv", "0.13.0"), base)),
    );

    expect(rowText("uv")).toContain("0.12.23 → 0.13.0");
    expect(rowText("Node.js")).not.toContain("→");
    expect(listed()[0]).toBe("uv");
  });
});

describe("ordering", () => {
  it("puts pinned tools first in pin order, then ordered ones, then the rest", async () => {
    shell(state(base, null), prefs(["uv", "git"], ["node"]));
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["uv", "Git", "Node.js"]);
  });

  it("keeps a pinned tool ahead of a changed one, and changed ahead of the unconfigured rest", async () => {
    shell(state(withVersion(base, "uv", "0.13.0"), base), prefs(["git"], []));
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["Git", "uv", "Node.js"]);
  });

  it("puts explicitly ordered tools ahead of changed ones", async () => {
    shell(state(withVersion(base, "uv", "0.13.0"), base), prefs([], ["node"]));
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["Node.js", "uv", "Git"]);
  });

  it("sorts the rest by name ignoring case, then by id", async () => {
    let scan = edit(base, "node", () => ({ name: "alpha" }));
    scan = edit(scan, "git", () => ({ name: "same" }));
    scan = edit(scan, "uv", () => ({ name: "SAME" }));
    // Reversed input: the result must not depend on the order the core printed.
    scan = { ...scan, tools: [...scan.tools].reverse() };
    shell(state(scan, null));
    render(<App />);
    await screen.findByText("alpha");
    expect(listed()).toEqual(["alpha", "same", "SAME"]);
  });

  it("never lifts a missing tool above the main list, however it is configured", async () => {
    shell(state(gone(base, "git"), base), prefs(["python", "git"], []));
    render(<App />);
    await screen.findByText("Node.js");
    expect(listed()).toEqual(["Node.js", "uv"]);
    fireEvent.click(screen.getByRole("button", { name: /Show not found/ }));
    // Pins order the missing section too, on its own.
    expect(namesIn("Not found")).toEqual(["Python", "Git"]);
  });

  it("applies the order to search results", async () => {
    const scan = edit(base, "uv", () => ({ name: "Git helper" }));
    shell(state(scan, null), prefs(["uv"], []));
    render(<App />);
    await screen.findByText("Git");
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "git" },
    });
    expect(listed()).toEqual(["Git helper", "Git"]);
  });

  it("uses the first position of an id that a list repeats", async () => {
    shell(state(base, null), prefs(["uv", "git", "uv"], ["git", "node"]));
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["uv", "Git", "Node.js"]);
  });

  it("reorders when a preferences-updated event arrives", async () => {
    shell(state(base, null));
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["Git", "Node.js", "uv"]);
    await act(() => emit("preferences-updated", prefs(["uv"], [])));
    expect(listed()).toEqual(["uv", "Git", "Node.js"]);
  });

  it("falls back to the default order when the config is invalid", async () => {
    shell(state(base, null), {
      config: { ...defaultsConfig, preferences: null },
      outcome: { kind: "ok" },
    });
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["Git", "Node.js", "uv"]);
  });
});
