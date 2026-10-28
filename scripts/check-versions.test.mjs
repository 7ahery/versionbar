// Behaviour of the version consistency gate, tested through its CLI against throwaway repos.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
const script = join(here, "check-versions.mjs");

function makeRepo({ pyproject = "0.1.0", cargo = "0.1.0", cargoLock = "0.1.0", uvLock = "0.1.0", pkg = "0.1.0", lockTop = "0.1.0", lockRoot = "0.1.0" } = {}) {
  const root = mkdtempSync(join(tmpdir(), "vb-ver-"));
  const put = (path, text) => {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), text);
  };
  put("core/pyproject.toml", `[project]\nname = "versionbar"\nversion = "${pyproject}"\n`);
  put("app/src-tauri/Cargo.toml", `[package]\nname = "tray-shell"\nversion = "${cargo}"\n`);
  put(
    "app/src-tauri/Cargo.lock",
    `[[package]]\nname = "other"\nversion = "9.9.9"\n\n[[package]]\nname = "tray-shell"\nversion = "${cargoLock}"\n`,
  );
  put(
    "core/uv.lock",
    `[[package]]\nname = "other"\nversion = "9.9.9"\n\n[[package]]\nname = "versionbar"\nversion = "${uvLock}"\nsource = { editable = "." }\n`,
  );
  put("package.json", JSON.stringify({ name: "w", version: pkg }));
  put(
    "package-lock.json",
    JSON.stringify({ name: "w", version: lockTop, packages: { "": { name: "w", version: lockRoot } } }),
  );
  return root;
}

const run = (root, ...args) =>
  spawnSync(process.execPath, [script, "--root", root, ...args], { encoding: "utf8" });

test("passes when every copy holds the same version", () => {
  const r = run(makeRepo());
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /0\.1\.0/);
});

test("fails and names the file whose version differs", () => {
  const r = run(makeRepo({ cargoLock: "0.0.9" }));
  assert.equal(r.status, 1);
  assert.match(r.stderr, /Cargo\.lock/);
  assert.match(r.stderr, /0\.0\.9/);
});

test("fails for each of the other copies too", () => {
  for (const [key, file] of [
    ["cargo", "Cargo\\.toml"],
    ["uvLock", "uv\\.lock"],
    ["pkg", "package\\.json"],
    ["lockTop", "package-lock\\.json"],
    ["lockRoot", "package-lock\\.json"],
  ]) {
    const r = run(makeRepo({ [key]: "0.3.0" }));
    assert.equal(r.status, 1, key);
    assert.match(r.stderr, new RegExp(file));
  }
});

test("treats semver prerelease and PEP 440 spellings as the same version", () => {
  const r = run(
    makeRepo({ pyproject: "0.2.0b1", cargo: "0.2.0-beta.1", cargoLock: "0.2.0-beta.1", uvLock: "0.2.0b1", pkg: "0.2.0-beta.1", lockTop: "0.2.0-beta.1", lockRoot: "0.2.0-beta.1" }),
  );
  assert.equal(r.status, 0, r.stderr);
});

test("a different prerelease number is a mismatch", () => {
  const r = run(
    makeRepo({ pyproject: "0.2.0b1", cargo: "0.2.0-beta.2", cargoLock: "0.2.0-beta.2", uvLock: "0.2.0b1", pkg: "0.2.0-beta.1", lockTop: "0.2.0-beta.1", lockRoot: "0.2.0-beta.1" }),
  );
  assert.equal(r.status, 1);
});

test("--tag accepts the matching release tag and rejects another", () => {
  const root = makeRepo({
    pyproject: "0.2.0-beta.1",
    cargo: "0.2.0-beta.1",
    cargoLock: "0.2.0-beta.1",
    uvLock: "0.2.0b1",
    pkg: "0.2.0-beta.1",
    lockTop: "0.2.0-beta.1",
    lockRoot: "0.2.0-beta.1",
  });
  assert.equal(run(root, "--tag", "v0.2.0-beta.1").status, 0);
  const bad = run(root, "--tag", "v0.2.1");
  assert.equal(bad.status, 1);
  assert.match(bad.stderr, /v0\.2\.1/);
});

test("fails clearly when a file has no version for its package", () => {
  const root = makeRepo();
  writeFileSync(join(root, "core/uv.lock"), `[[package]]\nname = "other"\nversion = "1.0.0"\n`);
  const r = run(root);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /uv\.lock/);
});

test("the real repository is consistent and release-please updates exactly the checked files", () => {
  const repoRoot = join(here, "..");
  const r = run(repoRoot);
  assert.equal(r.status, 0, r.stderr);
  const config = JSON.parse(readFileSync(join(repoRoot, "release-please-config.json"), "utf8"));
  const listed = config.packages["."]["extra-files"].map((f) => f.path);
  assert.deepEqual([...new Set(listed)].sort(), [
    "app/src-tauri/Cargo.lock",
    "app/src-tauri/Cargo.toml",
    "core/pyproject.toml",
    "core/uv.lock",
    "package-lock.json",
    "package.json",
  ]);
});
