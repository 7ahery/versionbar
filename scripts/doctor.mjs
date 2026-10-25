// `npm run doctor`: check the toolchain needed to contribute, using VersionBar's own
// `check` command (live, against this machine).
//
// The constraints are read from the repo's pins so they cannot drift from them:
// node from `engines.node`, npm's major from `packageManager`, the Rust pin from
// rust-toolchain.toml, uv's floor from the core's build-backend requirement.
//
// `--requirements` prints the requirement list as JSON and `--report` renders a
// `check --json` result read from stdin; the test suite uses both to exercise the
// aggregate check over a fake machine.

import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (path) => readFileSync(join(root, path), "utf8");

function pin(text, pattern, what) {
  const match = text.match(pattern);
  if (!match) {
    console.error(`doctor: cannot find the ${what} pin; update scripts/doctor.mjs.`);
    process.exit(2);
  }
  return match[1];
}

export function requirements() {
  const pkg = JSON.parse(read("package.json"));
  const npmMajor = pin(pkg.packageManager, /^npm@(\d+)\./, "npm (packageManager)");
  const rust = pin(read("rust-toolchain.toml"), /^channel\s*=\s*"([^"]+)"/m, "Rust (channel)");
  const uvFloor = pin(read("core/pyproject.toml"), /"uv_build(>=[\d.]+)/, "uv (build-system)");
  return [
    `node@${pkg.engines.node}`,
    `npm@>=${npmMajor}`,
    `uv@${uvFloor}`,
    `rustc@==${rust}`,
    `cargo@==${rust}`,
  ];
}

const SETUP = "See docs/setup/windows.md for the full setup.";
const REMEDIATION = {
  node: "Install or upgrade Node.js: winget install --id OpenJS.NodeJS.LTS --exact",
  npm: "Install or upgrade npm: npm install -g npm@11 (or reinstall Node.js LTS)",
  uv: "Install or upgrade uv: winget install --id astral-sh.uv --exact",
  rustc: "Install Rust: winget install --id Rustlang.Rustup --exact, then open a new terminal; inside the repo rustup installs the pinned toolchain from rust-toolchain.toml on the first cargo command",
  cargo: "Install Rust: winget install --id Rustlang.Rustup --exact, then open a new terminal; inside the repo rustup installs the pinned toolchain from rust-toolchain.toml on the first cargo command",
};

// Returns the text to print and the exit code.
export function report(result) {
  const lines = [];
  for (const r of result.requirements) {
    const detail = r.version ? `${r.tool} ${r.version}` : r.message;
    lines.push(`${r.passed ? "pass" : "FAIL"}  ${r.requirement}  ${detail}`);
  }
  const failed = result.requirements.filter((r) => !r.passed);
  if (failed.length === 0) {
    lines.push("", "All contributor tools are ready.");
    return { text: lines.join("\n"), code: 0 };
  }
  lines.push("", "How to fix:");
  const seen = new Set();
  for (const r of failed) {
    const fix = REMEDIATION[r.tool];
    if (fix && !seen.has(fix)) {
      seen.add(fix);
      lines.push(`  ${r.tool}: ${fix}`);
    }
  }
  lines.push(`  ${SETUP}`, "", "Open a new terminal after installing so PATH is refreshed.");
  return { text: lines.join("\n"), code: 1 };
}

function live() {
  // An empty config folder keeps the user's own VersionBar config (custom tools,
  // hidden tools, timeouts) from changing what the doctor reports.
  const emptyConfig = mkdtempSync(join(tmpdir(), "versionbar-doctor-"));
  try {
    const run = spawnSync(
      "uv",
      ["run", "--project", "core", "versionbar", "check", ...requirements(), "--json"],
      {
        cwd: root,
        encoding: "utf8",
        env: { ...process.env, APPDATA: emptyConfig, XDG_CONFIG_HOME: emptyConfig },
      },
    );
    if (run.error) {
      console.log(`FAIL  uv  not found\n\nHow to fix:\n  uv: ${REMEDIATION.uv}\n  ${SETUP}`);
      return 1;
    }
    let result;
    try {
      result = JSON.parse(run.stdout);
    } catch {
      console.error(`doctor: the check did not produce a result (exit ${run.status}).`);
      console.error(run.stderr);
      return 2;
    }
    const out = report(result);
    console.log(out.text);
    return out.code;
  } finally {
    rmSync(emptyConfig, { recursive: true, force: true });
  }
}

const arg = process.argv[2];
if (arg === "--requirements") {
  console.log(JSON.stringify(requirements()));
} else if (arg === "--report") {
  const out = report(JSON.parse(readFileSync(0, "utf8")));
  console.log(out.text);
  process.exitCode = out.code;
} else {
  process.exitCode = live();
}
