// The installer's Publisher entry in Windows Programs and Features comes from bundle.publisher.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
const conf = JSON.parse(readFileSync(join(here, "..", "app", "src-tauri", "tauri.conf.json"), "utf8"));

test("sets an explicit bundle publisher so Windows does not show one derived from the bundle id", () => {
  assert.equal(conf.bundle.publisher, "Michael Tahery");
});
