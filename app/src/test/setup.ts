import { clearMocks } from "@tauri-apps/api/mocks";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Each test installs its own IPC mock; never let one test's shell answers leak into the next.
afterEach(() => {
  cleanup();
  clearMocks();
});
