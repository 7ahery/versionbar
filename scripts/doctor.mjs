// `npm run doctor`: check the toolchain needed to contribute, using VersionBar's own
// `check` command (live, against this machine, with your normal VersionBar config).
//
// The constraints are read from the repo's pins so they cannot drift from them:
// node from `engines.node`, npm's major from `packageManager`, the Rust pin from
// rust-toolchain.toml. The repo has no uv CLI pin, so uv's floor is the lower bound of
// the build backend's `uv_build>=` range in core/pyproject.toml, the nearest thing to one.
//
// `--requirements` prints the requirement list as JSON and `--report` renders a
// `check --json` result read from stdin (or, with `--exit-code N`, the stderr of a
// `check` that failed); the test suite uses both to exercise the aggregate check over a
// fake machine.

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
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

const pkg = JSON.parse(read("package.json"));
const npmMajor = pin(pkg.packageManager, /^npm@(\d+)\./, "npm (packageManager)");

function requirements() {
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
const RUST_FIX =
  "Install Rust: winget install --id Rustlang.Rustup --exact, then open a new terminal; inside the repo rustup installs the pinned toolchain from rust-toolchain.toml on the first cargo command";
const REMEDIATION = {
  node: "Install or upgrade Node.js: winget install --id OpenJS.NodeJS.LTS --exact",
  npm: `Install or upgrade npm: npm install -g npm@${npmMajor} (or reinstall Node.js LTS)`,
  uv: "Install or upgrade uv: winget install --id astral-sh.uv --exact",
  rustc: RUST_FIX,
  cargo: RUST_FIX,
};

// Returns the text to print and the exit code.
function report(result) {
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

// Anything other than a check result: invalid config (exit 3) or an unexpected failure.
function explainFailure(status, stderr) {
  if (status === 3) {
    const text = [
      "The VersionBar config file cannot be used, so the check did not run:",
      "",
      stderr.trim(),
      "",
      "Fix the file, or run `npm run cli -- config` to see where it is.",
    ].join("\n");
    return { text, code: 1 };
  }
  return { text: `doctor: the check did not produce a result (exit ${status}).\n${stderr}`, code: 2 };
}

function live() {
  const run = spawnSync(
    "uv",
    ["run", "--project", "core", "versionbar", "check", ...requirements(), "--json"],
    { cwd: root, encoding: "utf8" },
  );
  if (run.error) {
    console.log(`FAIL  uv  not found\n\nHow to fix:\n  uv: ${REMEDIATION.uv}\n  ${SETUP}`);
    return 1;
  }
  let out;
  try {
    out = report(JSON.parse(run.stdout));
  } catch {
    out = explainFailure(run.status, run.stderr);
  }
  console.log(out.text);
  return out.code;
}

const arg = process.argv[2];
if (arg === "--requirements") {
  console.log(JSON.stringify(requirements()));
} else if (arg === "--report") {
  const input = readFileSync(0, "utf8");
  const failedWith = process.argv[3] === "--exit-code" ? Number(process.argv[4]) : null;
  const out = failedWith === null ? report(JSON.parse(input)) : explainFailure(failedWith, input);
  console.log(out.text);
  process.exitCode = out.code;
} else {
  process.exitCode = live();
}
