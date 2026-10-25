import { act, fireEvent, render, screen } from "@testing-library/react";
import { emit } from "@tauri-apps/api/event";
import { mockIPC } from "@tauri-apps/api/mocks";
import type { ConfigResult, ScanResult } from "schema";
import { afterEach, describe, expect, it } from "vitest";

import App from "./App";
import type { PreferencesState, ShellState } from "./shell";
import defaultsConfig from "./test/fixtures/config-windows-defaults.json";
import earlierScan from "./test/fixtures/list-windows.json";
import installsScan from "./test/fixtures/list-windows-installs.json";
import problemsScan from "./test/fixtures/list-windows-problems.json";
import providerOnlyScan from "./test/fixtures/list-windows-provider-only.json";

/**
 * Change highlighting and ordering, driven through the shell's state and preferences like
 * the running app. Transitions come from pairs of real captures of one machine
 * (test/fixtures/README.md):
 * - `earlier` to `installs`: Git 2.55.0.windows.2 to 2.56.0.windows.3; Node.js gains an
 *   install at the same active version.
 * - `installs` to `providerOnly`: Node.js goes from found to missing (and back in reverse).
 * - `installs` to `problems`: Git times out and uv exits with an error (recovered in reverse).
 * Python is missing in all of them. Only cases no capture can show are edited by hand, and
 * say so where they are.
 */
const earlier = earlierScan as ScanResult;
const installs = installsScan as ScanResult;
const problems = problemsScan as ScanResult;
const providerOnly = providerOnlyScan as ScanResult;
type Tool = ScanResult["tools"][number];

const GIT_OLD = "2.55.0.windows.2";
const GIT_NEW = "2.56.0.windows.3";

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

function showMissing() {
  fireEvent.click(screen.getByRole("button", { name: /Show not found/ }));
}

// Hand-edited scans, only where no capture can exist: a tool absent from a scan, a renamed
// tool, a reordered array. Nothing here invents a tool's output.
function without(scan: ScanResult, id: string): ScanResult {
  return { ...scan, tools: scan.tools.filter((tool) => tool.id !== id) };
}

function rename(scan: ScanResult, id: string, name: string): ScanResult {
  return {
    ...scan,
    tools: scan.tools.map((tool: Tool) =>
      tool.id === id ? { ...tool, name } : tool,
    ),
  };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("change highlighting", () => {
  it("shows no highlighting and the plain order when there is no previous scan", async () => {
    shell(state(installs, null));
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["Git", "Node.js", "uv"]);
    expect(document.body.textContent).not.toContain("→");
    expect(document.body.textContent).not.toMatch(/Newly|Recovered/);
  });

  it("shows an active version change as old → new and ignores an install that only appeared", async () => {
    shell(state(installs, earlier));
    render(<App />);
    await screen.findByText("Git");
    expect(rowText("Git")).toContain(`${GIT_OLD} → ${GIT_NEW}`);
    // Node.js gained an install at the same active version: not a change.
    expect(rowText("Node.js")).toContain("+1 install");
    expect(rowText("Node.js")).not.toContain("→");
    expect(rowText("Node.js")).not.toContain("Newly");
    expect(rowText("uv")).not.toContain("→");
  });

  it("does not highlight anything when the two scans agree", async () => {
    shell(state(installs, installs));
    render(<App />);
    await screen.findByText("Git");
    expect(document.body.textContent).not.toContain("→");
    expect(document.body.textContent).not.toMatch(/Newly|Recovered/);
  });

  it("calls a tool that was missing and is now found newly found", async () => {
    shell(state(installs, providerOnly));
    render(<App />);
    await screen.findByText("Git");
    expect(rowText("Node.js")).toContain("Newly found");
    expect(rowText("Node.js")).toContain("24.21.0");
    expect(listed()[0]).toBe("Node.js");
  });

  it("calls a tool absent from the previous scan newly found", async () => {
    // No capture lists fewer tools than the catalog; this is a tool added to the catalog.
    shell(state(installs, without(installs, "uv")));
    render(<App />);
    await screen.findByText("Git");
    expect(rowText("uv")).toContain("Newly found");
    expect(listed()[0]).toBe("uv");
  });

  it("calls a tool that was found and is now missing newly missing, in the missing section", async () => {
    shell(state(providerOnly, installs));
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["Git", "uv"]);
    showMissing();
    // Changed first within the section, ahead of Python which was missing before too.
    expect(namesIn("Not found")).toEqual(["Node.js", "Python"]);
    expect(rowText("Node.js")).toContain("Newly missing (was 24.21.0)");
    expect(rowText("Python")).not.toContain("Newly");
  });

  it("calls tools that were found and now time out or error newly failing, in the main list", async () => {
    shell(state(problems, installs));
    render(<App />);
    await screen.findByText("Node.js");
    // Both failing tools sort ahead of unchanged Node.js, which the name order alone would
    // put between them.
    expect(listed()).toEqual(["Git", "uv", "Node.js"]);
    expect(rowText("Git")).toContain("Timed out");
    expect(rowText("Git")).toContain(`Newly failing (was ${GIT_NEW})`);
    expect(rowText("uv")).toContain("Error");
    expect(rowText("uv")).toContain("Newly failing (was 0.12.23)");
  });

  it("calls a tool absent from the previous scan that now fails newly failing", async () => {
    shell(state(problems, without(problems, "uv")));
    render(<App />);
    await screen.findByText("Node.js");
    expect(rowText("uv")).toContain("Newly failing");
    expect(rowText("uv")).not.toContain("was");
  });

  it("does not highlight tools that failed before and still fail", async () => {
    shell(state(problems, problems));
    render(<App />);
    await screen.findByText("Node.js");
    expect(document.body.textContent).not.toMatch(/Newly/);
    expect(listed()).toEqual(["Git", "Node.js", "uv"]);
  });

  it("calls tools that were failing and are now found recovered, not upgraded and with no earlier version", async () => {
    shell(state(installs, problems));
    render(<App />);
    await screen.findByText("Node.js");
    const expected: [string, string][] = [
      ["Git", GIT_NEW],
      ["uv", "0.12.23"],
    ];
    for (const [name, version] of expected) {
      const text = rowText(name);
      expect(text).toContain("Recovered");
      expect(text).toContain(version);
      expect(text).not.toContain("→");
      expect(text).not.toMatch(/upgrad/i);
    }
    expect(listed()).toEqual(["Git", "uv", "Node.js"]);
  });

  it("restores highlighting from a saved pair at launch and follows scan-updated", async () => {
    shell(state(installs, earlier));
    render(<App />);
    await screen.findByText("Git");
    expect(rowText("Git")).toContain(`${GIT_OLD} → ${GIT_NEW}`);

    await act(() => emit("scan-updated", state(problems, installs)));

    expect(rowText("Git")).not.toContain("→");
    expect(rowText("Git")).toContain("Newly failing");
  });
});

describe("ordering", () => {
  it("puts pinned tools first in pin order, then ordered ones, then the rest", async () => {
    shell(state(installs, null), prefs(["uv", "git"], ["node"]));
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["uv", "Git", "Node.js"]);
  });

  it("keeps a pinned tool ahead of changed ones", async () => {
    shell(state(problems, installs), prefs(["node"], []));
    render(<App />);
    await screen.findByText("Node.js");
    expect(listed()).toEqual(["Node.js", "Git", "uv"]);
  });

  it("puts explicitly ordered tools ahead of changed ones", async () => {
    shell(state(problems, installs), prefs([], ["node"]));
    render(<App />);
    await screen.findByText("Node.js");
    expect(listed()).toEqual(["Node.js", "Git", "uv"]);
  });

  it("sorts the rest by name ignoring case, then by id", async () => {
    // Names that differ only in case, and a reversed array: no capture has either.
    let scan = rename(installs, "node", "alpha");
    scan = rename(scan, "git", "same");
    scan = rename(scan, "uv", "SAME");
    scan = { ...scan, tools: [...scan.tools].reverse() };
    shell(state(scan, null));
    render(<App />);
    await screen.findByText("alpha");
    expect(listed()).toEqual(["alpha", "same", "SAME"]);
  });

  it("never lifts a missing tool above the main list, however it is configured", async () => {
    shell(state(providerOnly, installs), prefs(["python", "node"], []));
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["Git", "uv"]);
    showMissing();
    // Pins order the missing section too, on its own.
    expect(namesIn("Not found")).toEqual(["Python", "Node.js"]);
  });

  it("applies the order to search results", async () => {
    // A second tool whose name matches "git": no capture has two such tools.
    const scan = rename(installs, "uv", "Git helper");
    shell(state(scan, null), prefs(["uv"], []));
    render(<App />);
    await screen.findByText("Git");
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "git" },
    });
    expect(listed()).toEqual(["Git helper", "Git"]);
  });

  it("uses the first position of an id that a list repeats", async () => {
    shell(state(installs, null), prefs(["uv", "git", "uv"], ["git", "node"]));
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["uv", "Git", "Node.js"]);
  });

  it("reorders when a preferences-updated event arrives", async () => {
    shell(state(installs, null));
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["Git", "Node.js", "uv"]);
    await act(() => emit("preferences-updated", prefs(["uv"], [])));
    expect(listed()).toEqual(["uv", "Git", "Node.js"]);
  });

  it("falls back to the default order when the config is invalid", async () => {
    shell(state(installs, null), {
      config: { ...defaultsConfig, preferences: null },
      outcome: { kind: "ok" },
    });
    render(<App />);
    await screen.findByText("Git");
    expect(listed()).toEqual(["Git", "Node.js", "uv"]);
  });
});
