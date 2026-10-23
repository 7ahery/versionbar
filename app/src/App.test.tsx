import { render, screen, waitFor } from "@testing-library/react";
import { mockIPC } from "@tauri-apps/api/mocks";
import { describe, expect, it } from "vitest";

import App from "./App";

describe("popup", () => {
  it("shows the product name and the version the shell reports", async () => {
    mockIPC((cmd) => {
      if (cmd === "plugin:app|version") return "0.1.0";
      throw new Error(`unexpected command ${cmd}`);
    });

    render(<App />);

    expect(screen.getByRole("heading", { name: "VersionBar" })).toBeDefined();
    expect(await screen.findByText("v0.1.0")).toBeDefined();
  });

  it("still renders when the shell cannot report its version", async () => {
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
});
