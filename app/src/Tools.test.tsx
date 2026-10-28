import { fireEvent, render, screen, within } from "@testing-library/react";
import { mockIPC } from "@tauri-apps/api/mocks";
import type { ScanResult } from "schema";
import { afterEach, describe, expect, it } from "vitest";

import App from "./App";
import type { ShellState } from "./shell";
import installsScan from "./test/fixtures/list-windows-installs.json";
import problemsScan from "./test/fixtures/list-windows-problems.json";
import providerOnlyScan from "./test/fixtures/list-windows-provider-only.json";

/**
 * Real `versionbar list --json` output from one Windows machine (profile path redacted):
 * - `installs`: Git twice on PATH; Node.js active from nvm's install folder plus nvm's shim.
 * - `problems`: the same machine with a config making Git time out and uv exit with an error.
 * - `providerOnly`: nvm's folders taken off PATH, so Node.js is missing while nvm still
 *   holds a version (no active install, one provider install).
 * Python is a Microsoft Store placeholder, so it is missing in all three.
 */
const installs = installsScan as ScanResult;
const problems = problemsScan as ScanResult;
const providerOnly = providerOnlyScan as ScanResult;

const GIT_UCRT = String.raw`C:\Program Files\Git\ucrt64\bin\git.exe`;
const GIT_CMD = String.raw`C:\Program Files\Git\cmd\git.exe`;
const NODE_INSTALL = String.raw`%USERPROFILE%\AppData\Local\Author Software\nvm\installs\v24.21.0\node.exe`;
const NODE_SHIM = String.raw`%USERPROFILE%\AppData\Local\Author Software\nvm\.nodejs\node.exe`;

interface Call {
  cmd: string;
  args: unknown;
}

/**
 * Answers the shell's commands like Rust does and records every call. With `folderError`,
 * `open_containing_folder` fails with that message instead of succeeding.
 */
function shell(current: ScanResult, folderError?: string) {
  const calls: Call[] = [];
  const state: ShellState = {
    scanning: false,
    current,
    previous: null,
    outcome: { kind: "ok" },
  };
  mockIPC(
    (cmd, args) => {
      calls.push({ cmd, args });
      if (cmd === "plugin:app|version") return "0.1.0";
      if (cmd === "get_state") return state;
      if (cmd === "open_containing_folder") {
        if (folderError === undefined) return null;
        // Tauri rejects with the error string the Rust command returned, not an Error.
        // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors
        return Promise.reject(folderError);
      }
      throw new Error(`unexpected command ${cmd}`);
    },
    { shouldMockEvents: true },
  );
  return calls;
}

/** The row of the named tool. */
function row(name: string): HTMLElement {
  const item = screen
    .getByText(name, { selector: "[data-tool-name]" })
    .closest("li");
  if (!item) throw new Error(`no row for ${name}`);
  return item;
}

/** The expanded details of the install at `path`. */
function install(path: string): HTMLElement {
  const item = screen.getByText(path).closest("li");
  if (!item) throw new Error(`no install at ${path}`);
  return item;
}

afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("tool rows", () => {
  it("show the name, the active version and how many other installs there are", async () => {
    shell(installs);

    render(<App />);

    await screen.findByText("Git");
    expect(within(row("Git")).getByText("2.56.0.windows.3")).toBeDefined();
    expect(within(row("Git")).getByText("+1 install")).toBeDefined();
    expect(within(row("Node.js")).getByText("24.21.0")).toBeDefined();
    expect(within(row("Node.js")).getByText("+1 install")).toBeDefined();
    expect(within(row("uv")).getByText("0.12.23")).toBeDefined();
    expect(within(row("uv")).queryByText(/install/)).toBeNull();
  });

  it("expand to every install with its version, path and source", async () => {
    shell(installs);
    render(<App />);
    await screen.findByText("Git");
    expect(screen.queryByText(GIT_CMD)).toBeNull();

    fireEvent.click(within(row("Git")).getByRole("button", { name: /Git/ }));

    const active = install(GIT_UCRT);
    expect(within(active).getByText("2.56.0.windows.3")).toBeDefined();
    expect(within(active).getByText("Active")).toBeDefined();
    expect(within(active).getByText("On PATH")).toBeDefined();
    const other = install(GIT_CMD);
    expect(within(other).getByText("2.56.0.windows.3")).toBeDefined();
    expect(within(other).getByText("On PATH")).toBeDefined();
    expect(within(other).queryByText("Active")).toBeNull();
  });

  it("collapse again", async () => {
    shell(installs);
    render(<App />);
    await screen.findByText("Git");
    const toggle = within(row("Git")).getByRole("button", { name: /Git/ });

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle);

    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(GIT_CMD)).toBeNull();
  });

  it("name the manager whose shim serves an install", async () => {
    shell(installs);
    render(<App />);
    await screen.findByText("Node.js");

    fireEvent.click(
      within(row("Node.js")).getByRole("button", { name: /Node\.js/ }),
    );

    expect(within(install(NODE_INSTALL)).getByText("Active")).toBeDefined();
    expect(within(install(NODE_INSTALL)).queryByText(/via/)).toBeNull();
    expect(within(install(NODE_SHIM)).getByText("via nvm")).toBeDefined();
    expect(within(install(NODE_SHIM)).getByText("On PATH")).toBeDefined();
  });

  it("explain a failed tool with the core's message when expanded", async () => {
    shell(problems);
    render(<App />);
    await screen.findByText("uv");

    fireEvent.click(within(row("uv")).getByRole("button", { name: /uv/ }));

    expect(
      within(row("uv")).getByText(
        /uv\.exe exited with code 2: error: unexpected argument '--no-such-flag' found/,
      ),
    ).toBeDefined();
  });
});

describe("tools that are not working", () => {
  it("say timed out or error, and stay in the main list apart from missing tools", async () => {
    shell(problems);

    render(<App />);

    await screen.findByText("Git");
    expect(within(row("Git")).getByText("Timed out")).toBeDefined();
    expect(within(row("uv")).getByText("Error")).toBeDefined();
    expect(within(row("Node.js")).getByText("24.21.0")).toBeDefined();
    const main = screen.getByRole("list", { name: "Tools" });
    expect(within(main).getByText("Git")).toBeDefined();
    expect(within(main).getByText("uv")).toBeDefined();
    expect(within(main).queryByText("Python")).toBeNull();
  });
});

describe("install actions", () => {
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

  async function expandGit() {
    render(<App />);
    await screen.findByText("Git");
    fireEvent.click(within(row("Git")).getByRole("button", { name: /Git/ }));
  }

  function action(path: string, name: string) {
    fireEvent.click(within(install(path)).getByRole("button", { name }));
  }

  it("copy the version of that install", async () => {
    const copied = clipboard();
    shell(installs);
    await expandGit();

    action(GIT_CMD, "Copy version");

    expect(await screen.findByText("Version copied")).toBeDefined();
    expect(copied).toEqual(["2.56.0.windows.3"]);
  });

  it("copy the path of that install", async () => {
    const copied = clipboard();
    shell(installs);
    await expandGit();

    action(GIT_CMD, "Copy path");

    expect(await screen.findByText("Path copied")).toBeDefined();
    expect(copied).toEqual([GIT_CMD]);
  });

  it("say so when the clipboard refuses", async () => {
    clipboard(true);
    shell(installs);
    await expandGit();

    action(GIT_UCRT, "Copy path");

    expect(
      await screen.findByText("Could not copy. Select the text instead."),
    ).toBeDefined();
  });

  it("ask the shell to open the folder of exactly that install", async () => {
    const calls = shell(installs);
    await expandGit();

    action(GIT_CMD, "Open containing folder");

    expect(await screen.findByText("Opened in Explorer")).toBeDefined();
    expect(
      calls.filter((call) => call.cmd === "open_containing_folder"),
    ).toEqual([{ cmd: "open_containing_folder", args: { path: GIT_CMD } }]);
  });

  it("show why the shell could not open the folder", async () => {
    shell(installs, "This install no longer exists.");
    await expandGit();

    action(GIT_UCRT, "Open containing folder");

    expect(
      await screen.findByText("This install no longer exists."),
    ).toBeDefined();
  });
});

describe("search", () => {
  function search(text: string) {
    fireEvent.change(screen.getByRole("searchbox", { name: "Search tools" }), {
      target: { value: text },
    });
  }

  it("refocuses the search box each time the popup window regains focus", async () => {
    shell(installs);
    render(<App />);
    await screen.findByText("Git");
    const box = screen.getByRole("searchbox", { name: "Search tools" });
    box.blur();
    expect(document.activeElement).not.toBe(box);

    fireEvent.focus(window);

    expect(document.activeElement).toBe(box);
  });

  it("keeps only the tools whose name matches, ignoring case", async () => {
    shell(installs);
    render(<App />);
    await screen.findByText("Git");

    search("NODE");

    expect(row("Node.js")).toBeDefined();
    expect(screen.queryByText("Git")).toBeNull();
    expect(screen.queryByText("uv")).toBeNull();
  });

  it("finds missing tools without opening their section", async () => {
    shell(installs);
    render(<App />);
    await screen.findByText("Git");

    search("pyth");

    const missing = screen.getByRole("list", { name: "Not found" });
    expect(within(missing).getByText("Python")).toBeDefined();
    expect(screen.queryByText("Git")).toBeNull();
  });

  it("says when nothing matches", async () => {
    shell(installs);
    render(<App />);
    await screen.findByText("Git");

    search("kubectl");

    expect(screen.getByText("No tools match “kubectl”.")).toBeDefined();
    expect(screen.queryByRole("button", { name: /not found/ })).toBeNull();
  });

  it("is cleared with Escape", async () => {
    shell(installs);
    render(<App />);
    await screen.findByText("Git");
    search("node");

    fireEvent.keyDown(screen.getByRole("searchbox", { name: "Search tools" }), {
      key: "Escape",
    });

    expect(row("Git")).toBeDefined();
    expect(row("uv")).toBeDefined();
  });
});

describe("missing tools", () => {
  it("are hidden behind a toggle that counts them", async () => {
    shell(installs);
    render(<App />);
    await screen.findByText("Git");
    expect(screen.queryByText("Python")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Show not found (1)" }));

    const missing = screen.getByRole("list", { name: "Not found" });
    expect(within(missing).getByText("Python")).toBeDefined();
    expect(within(row("Python")).getByText("Not found")).toBeDefined();
  });

  it("can be hidden again", async () => {
    shell(installs);
    render(<App />);
    await screen.findByText("Git");
    fireEvent.click(screen.getByRole("button", { name: "Show not found (1)" }));

    fireEvent.click(screen.getByRole("button", { name: "Hide not found (1)" }));

    expect(screen.queryByText("Python")).toBeNull();
  });

  it("explain why they are missing", async () => {
    shell(installs);
    render(<App />);
    await screen.findByText("Git");
    fireEvent.click(screen.getByRole("button", { name: "Show not found (1)" }));

    fireEvent.click(
      within(row("Python")).getByRole("button", { name: /Python/ }),
    );

    expect(
      within(row("Python")).getByText(
        "only Microsoft Store placeholders found on PATH (looked for: python, python3)",
      ),
    ).toBeDefined();
  });

  it("still list the versions a manager holds, none of them active", async () => {
    shell(providerOnly);
    render(<App />);
    await screen.findByText("Git");
    fireEvent.click(screen.getByRole("button", { name: "Show not found (2)" }));
    const node = row("Node.js");
    expect(within(node).getByText("Not found")).toBeDefined();
    expect(within(node).getByText("+1 install")).toBeDefined();

    fireEvent.click(within(node).getByRole("button", { name: /Node\.js/ }));

    expect(within(install(NODE_INSTALL)).getByText("24.21.0")).toBeDefined();
    expect(within(install(NODE_INSTALL)).getByText("From nvm")).toBeDefined();
    expect(within(install(NODE_INSTALL)).queryByText("Active")).toBeNull();
    expect(
      within(node).getByText("not found on PATH (looked for: node)"),
    ).toBeDefined();
  });
});
