// Writes latest.json, the static update feed the Tauri updater reads (ADR 0010), for one signed
// release build. The release workflow runs it after a signed `tauri build`; the feed is then
// attached to the GitHub release next to the installer it names.
//
// The feed carries the signature file's content, not a link to it: the updater verifies the
// downloaded installer against that string with the public key in tauri.conf.json.
//
// Usage: node scripts/updater-feed.mjs --installer <path to *-setup.exe> --tag <vX.Y.Z>
//          --repo <owner/name> --out <latest.json> [--notes-file <path>] [--pub-date <RFC 3339>]
//
// Notes come from a file because release notes are multi-line Markdown that may start with
// "---", which an argument parser would take for a flag.
import { readFileSync, writeFileSync } from "node:fs";
import { basename } from "node:path";

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`unexpected argument "${key}"`);
    const value = argv[i + 1];
    if (value === undefined || value.startsWith("--")) throw new Error(`${key} needs a value`);
    args[key.slice(2)] = value;
    i++;
  }
  for (const required of ["installer", "tag", "repo", "out"]) {
    if (!args[required]) throw new Error(`--${required} is required`);
  }
  return args;
}

function buildFeed({ installer, tag, repo, notes = "", pubDate, signature }) {
  const name = basename(installer);
  return {
    version: tag.replace(/^v/, ""),
    notes,
    pub_date: pubDate,
    platforms: {
      "windows-x86_64": {
        signature,
        url: `https://github.com/${repo}/releases/download/${encodeURIComponent(tag)}/${encodeURIComponent(name)}`,
      },
    },
  };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const signature = readFileSync(`${args.installer}.sig`, "utf8").trim();
  // Whole seconds: RFC 3339 allows fractions, but there is nothing to gain from them here.
  const pubDate = args["pub-date"] ?? new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  const notes = args["notes-file"] ? readFileSync(args["notes-file"], "utf8").trim() : "";
  const feed = buildFeed({ ...args, notes, pubDate, signature });
  writeFileSync(args.out, `${JSON.stringify(feed, null, 2)}\n`);
  console.log(`wrote ${args.out} for ${feed.version}`);
}

try {
  main();
} catch (err) {
  console.error(`updater-feed: ${err.message}`);
  process.exit(1);
}
