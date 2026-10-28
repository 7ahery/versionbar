// Version consistency gate: core/pyproject.toml is the source of truth, and every other copy
// of the version must agree with it. Run in CI on every PR (so a release PR that bumped only
// some files fails) and again by the release workflow before anything is published.
//
// Spellings are compared normalised because release-please writes semver (0.2.0-beta.1) while
// Python tooling normalises to PEP 440 (0.2.0b1); both are the same release.
//
// Usage: node scripts/check-versions.mjs [--root <dir>] [--tag <vX.Y.Z>]
import { readFileSync } from "node:fs";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// release-please-config.json `extra-files` must list exactly these paths (the test enforces it).
export const VERSION_FILES = [
  "core/pyproject.toml",
  "app/src-tauri/Cargo.toml",
  "app/src-tauri/Cargo.lock",
  "core/uv.lock",
  "package.json",
  "package-lock.json",
];

const PRE = { alpha: "a", a: "a", beta: "b", b: "b", rc: "rc", c: "rc" };

export function normalise(raw) {
  const m = /^v?(\d+\.\d+\.\d+)(?:[-.]?(alpha|beta|rc|a|b|c)[.]?(\d+))?$/.exec(raw.trim());
  if (!m) throw new Error(`unrecognised version "${raw}"`);
  return m[2] ? `${m[1]}${PRE[m[2]]}${m[3]}` : m[1];
}

// Minimal TOML reading: the files are machine-written with one `key = "value"` per line, and a
// full parser would be a new dependency for two lookups.
function versionInTable(text, header) {
  let inTable = false;
  for (const line of text.split(/\r?\n/)) {
    if (line.startsWith("[")) inTable = line.trim() === header;
    else if (inTable) {
      const m = /^version\s*=\s*"([^"]+)"/.exec(line);
      if (m) return m[1];
    }
  }
  return undefined;
}

function versionInPackageBlock(text, name) {
  for (const block of text.split(/^\[\[package\]\]\s*$/m).slice(1)) {
    const n = /^name\s*=\s*"([^"]+)"/m.exec(block);
    if (n && n[1] === name) return /^version\s*=\s*"([^"]+)"/m.exec(block)?.[1];
  }
  return undefined;
}

const READERS = {
  "core/pyproject.toml": (t) => versionInTable(t, "[project]"),
  "app/src-tauri/Cargo.toml": (t) => versionInTable(t, "[package]"),
  "app/src-tauri/Cargo.lock": (t) => versionInPackageBlock(t, "tray-shell"),
  "core/uv.lock": (t) => versionInPackageBlock(t, "versionbar"),
  "package.json": (t) => JSON.parse(t).version,
  // Both the top-level and the root-workspace entry carry the version; npm ci rejects a lock
  // whose root entry disagrees with package.json.
  "package-lock.json": (t) => {
    const lock = JSON.parse(t);
    return [lock.version, lock.packages?.[""]?.version];
  },
};

export function checkVersions(root, tag) {
  const problems = [];
  const found = [];
  for (const file of VERSION_FILES) {
    let raws;
    try {
      raws = [READERS[file](readFileSync(join(root, file), "utf8"))].flat();
    } catch (e) {
      problems.push(`${file}: cannot read (${e.message})`);
      continue;
    }
    for (const raw of raws) {
      if (typeof raw !== "string") {
        problems.push(`${file}: no version found`);
        continue;
      }
      try {
        found.push({ file, raw, norm: normalise(raw) });
      } catch (e) {
        problems.push(`${file}: ${e.message}`);
      }
    }
  }
  const truth = found.find((v) => v.file === VERSION_FILES[0]);
  if (truth) {
    for (const { file, ...v } of found) {
      if (v.norm !== truth.norm) {
        problems.push(`${file}: version ${v.raw} differs from ${VERSION_FILES[0]} (${truth.raw})`);
      }
    }
    if (tag) {
      try {
        if (normalise(tag) !== truth.norm) problems.push(`tag ${tag} does not match version ${truth.raw}`);
      } catch (e) {
        problems.push(`tag ${tag}: ${e.message}`);
      }
    }
  }
  return { version: truth?.raw, problems };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const opt = (name) => (args.includes(name) ? args[args.indexOf(name) + 1] : undefined);
  const root = opt("--root") ?? join(dirname(fileURLToPath(import.meta.url)), "..");
  const { version, problems } = checkVersions(root, opt("--tag"));
  if (problems.length) {
    console.error(`Version check failed:\n${problems.map((p) => `  - ${p}`).join("\n")}`);
    process.exit(1);
  }
  console.log(`All version copies agree: ${version}`);
}
