// Behaviour of the updater feed writer, tested through its CLI against throwaway build folders.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
const script = join(here, "updater-feed.mjs");

// A minisign signature as `tauri signer sign` writes it: base64 of the two-part text file.
const SIG = "dW50cnVzdGVkIGNvbW1lbnQ6IHNpZ25hdHVyZSBmcm9tIHRhdXJpIHNlY3JldCBrZXkKUlVUVEw=";

function makeBuild({ installer = "VersionBar_0.2.0_x64-setup.exe", sig = SIG } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "vb-feed-"));
  writeFileSync(join(dir, installer), "MZ");
  if (sig !== null) writeFileSync(join(dir, `${installer}.sig`), `${sig}\n`);
  const notes = join(dir, "notes.md");
  // A leading "---" would look like a flag if notes were passed on the command line.
  writeFileSync(notes, "---\n### Bug Fixes\n\n* scan faster\n");
  return { dir, installer: join(dir, installer), notes, out: join(dir, "latest.json") };
}

const run = (...args) => spawnSync(process.execPath, [script, ...args], { encoding: "utf8" });

test("writes a Tauri static feed pointing at the installer on the tagged release", () => {
  const b = makeBuild();
  const r = run(
    "--installer", b.installer,
    "--tag", "v0.2.0",
    "--repo", "7ahery/versionbar",
    "--notes-file", b.notes,
    "--pub-date", "2026-10-28T09:30:00Z",
    "--out", b.out,
  );
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(JSON.parse(readFileSync(b.out, "utf8")), {
    version: "0.2.0",
    notes: "---\n### Bug Fixes\n\n* scan faster",
    pub_date: "2026-10-28T09:30:00Z",
    platforms: {
      "windows-x86_64": {
        signature: SIG,
        url: "https://github.com/7ahery/versionbar/releases/download/v0.2.0/VersionBar_0.2.0_x64-setup.exe",
      },
    },
  });
});

test("fails and writes no feed when the installer has no signature", () => {
  const b = makeBuild({ sig: null });
  const r = run("--installer", b.installer, "--tag", "v0.2.0", "--repo", "7ahery/versionbar", "--out", b.out);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /\.sig/);
  assert.equal(existsSync(b.out), false);
});

test("the app's updater config reads this feed from the latest public release", () => {
  const conf = JSON.parse(readFileSync(join(here, "..", "app/src-tauri/tauri.conf.json"), "utf8"));
  assert.deepEqual(conf.plugins.updater.endpoints, [
    "https://github.com/7ahery/versionbar/releases/latest/download/latest.json",
  ]);
  // The config holds the public half only; a private key would never decode to this.
  const pubkey = Buffer.from(conf.plugins.updater.pubkey, "base64").toString("utf8");
  assert.match(pubkey, /^untrusted comment: minisign public key: [0-9A-F]{16}\n\S+\n$/);
  // Ordinary builds must not need the signing secret; only the release build turns this on.
  assert.notEqual(conf.bundle.createUpdaterArtifacts, true);
});
