// The installed app builds the core from only the files bundle.resources ships. A file that
// pyproject.toml references but the bundle lacks (v0.1.0: LICENSE) breaks every scan.
import assert from "node:assert/strict";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
const confDir = join(here, "..", "app", "src-tauri");
const conf = JSON.parse(readFileSync(join(confDir, "tauri.conf.json"), "utf8"));

test("the core builds and runs from exactly the files bundle.resources ships", () => {
  const root = mkdtempSync(join(tmpdir(), "versionbar-bundle-"));
  try {
    for (const [from, to] of Object.entries(conf.bundle.resources)) {
      const dest = join(root, to);
      mkdirSync(dirname(dest), { recursive: true });
      cpSync(resolve(confDir, from), dest, { recursive: true });
    }
    // Same flags as core_command in app/src-tauri/src/scan.rs.
    const env = { ...process.env, UV_PROJECT_ENVIRONMENT: join(root, "env") };
    delete env.VIRTUAL_ENV;
    const result = spawnSync(
      "uv",
      [
        "run", "--frozen", "--no-dev", "--managed-python",
        "--project", join(root, "core"),
        "--", "versionbar", "config", "--json",
      ],
      { env, encoding: "utf8" },
    );
    assert.equal(result.status, 0, result.stderr);
    JSON.parse(result.stdout);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
