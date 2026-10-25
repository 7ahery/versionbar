import { useMemo } from "react";
import type { ScanResult } from "schema";

/**
 * What the popup derives from one scan result. The rows come from one derived pipeline
 * (search, then the missing split), so later steps such as hiding, pinning and reordering
 * can join it without a state library.
 */

export type Tool = ScanResult["tools"][number];
export type Install = Tool["installs"][number];

/**
 * How a tool differs between the saved previous scan and the current one. Only the pair the
 * shell persists is compared, so nothing here says "since version X" or "since an update":
 * `from` is the previous scan's active version, never a guess about earlier history.
 * - `changed`: active version differs (`from` to `to`).
 * - `found`: absent or missing before, found now.
 * - `recovered`: was failing (error, timeout), found now. Not an upgrade: no earlier version.
 * - `missing`: was found, now missing (`from` is its previous version).
 * - `failing`: was found or missing, now failing (`from` is the previous version, if any).
 */
export type Change =
  | { kind: "changed"; from: string; to: string }
  | { kind: "found" }
  | { kind: "recovered" }
  | { kind: "missing"; from: string | null }
  | { kind: "failing"; from: string | null };

/** What the config's `pinned` and `order` lists say (docs/app/ordering.md). */
export interface Arrangement {
  pinned: readonly string[];
  order: readonly string[];
}

const failed = (tool: Tool) =>
  tool.status === "error" || tool.status === "timeout";

function changeOf(current: Tool, previous: Tool | undefined): Change | null {
  const now = current.active?.version ?? null;
  const was = previous?.active?.version ?? null;
  if (current.status === "found") {
    if (!previous || previous.status === "missing") return { kind: "found" };
    if (failed(previous)) return { kind: "recovered" };
    if (
      previous.status === "found" &&
      now !== null &&
      was !== null &&
      now !== was
    ) {
      return { kind: "changed", from: was, to: now };
    }
    return null;
  }
  // A tool the previous scan did not list, or that was already missing or failing in the
  // same way, has nothing to announce.
  if (!previous) return null;
  if (current.status === "missing" && previous.status === "found") {
    return { kind: "missing", from: was };
  }
  if (failed(current) && !failed(previous)) {
    return { kind: "failing", from: previous.status === "found" ? was : null };
  }
  return null;
}

/** Changes by tool id; empty without a previous scan, so there is nothing to highlight. */
export function changesBetween(
  current: Tool[],
  previous: Tool[] | null,
): Map<string, Change> {
  const changes = new Map<string, Change>();
  if (!previous) return changes;
  const before = new Map(previous.map((tool) => [tool.id, tool]));
  for (const tool of current) {
    const change = changeOf(tool, before.get(tool.id));
    if (change) changes.set(tool.id, change);
  }
  return changes;
}

/** Position of each id in the lists; an id repeated keeps its first position. */
function ranks(ids: readonly string[]): Map<string, number> {
  const rank = new Map<string, number>();
  for (const id of ids) if (!rank.has(id)) rank.set(id, rank.size);
  return rank;
}

/**
 * Sorts one section: pinned ids first in pin order, then ordered ids in their order, then
 * the rest changed-first, by name ignoring case, and by id. A total order, so the result
 * never depends on the order the core printed. The caller sorts the main list and the
 * missing section separately, which is what keeps a pinned or changed missing tool below
 * the main list.
 */
export function arrange(
  tools: Tool[],
  changes: ReadonlyMap<string, Change>,
  { pinned, order }: Arrangement,
): Tool[] {
  const pin = ranks(pinned);
  const place = ranks(order);
  const tier = (tool: Tool) =>
    pin.has(tool.id) ? 0 : place.has(tool.id) ? 1 : 2;
  const position = (tool: Tool) => pin.get(tool.id) ?? place.get(tool.id) ?? 0;
  return [...tools].sort((a, b) => {
    const byTier = tier(a) - tier(b);
    if (byTier !== 0) return byTier;
    if (tier(a) < 2) return position(a) - position(b);
    const byChange = Number(changes.has(b.id)) - Number(changes.has(a.id));
    if (byChange !== 0) return byChange;
    const nameA = a.name.toLowerCase();
    const nameB = b.name.toLowerCase();
    if (nameA !== nameB) return nameA < nameB ? -1 : 1;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
}

/**
 * The rows to show for a search: the tools whose name or id contains `query` (ignoring case
 * and surrounding spaces), split into the main list and the missing section, each arranged
 * by `arrange`.
 */
export function useToolRows(
  tools: Tool[],
  previous: Tool[] | null,
  arrangement: Arrangement,
  query: string,
): { listed: Tool[]; missing: Tool[]; changes: Map<string, Change> } {
  const { pinned, order } = arrangement;
  return useMemo(() => {
    const changes = changesBetween(tools, previous);
    const needle = query.trim().toLowerCase();
    const found = needle
      ? tools.filter(
          (tool) =>
            tool.name.toLowerCase().includes(needle) ||
            tool.id.toLowerCase().includes(needle),
        )
      : tools;
    const split = splitMissing(found);
    const sort = (section: Tool[]) =>
      arrange(section, changes, { pinned, order });
    return {
      listed: sort(split.listed),
      missing: sort(split.missing),
      changes,
    };
  }, [tools, previous, pinned, order, query]);
}

/**
 * Missing tools go to their own section; every other status (found, error, timeout and any
 * added later) stays in the main list, so a broken tool is never tucked away as absent.
 */
function splitMissing(tools: Tool[]): { listed: Tool[]; missing: Tool[] } {
  const listed: Tool[] = [];
  const missing: Tool[] = [];
  for (const tool of tools) {
    (tool.status === "missing" ? missing : listed).push(tool);
  }
  return { listed, missing };
}

/**
 * The installs besides the active one. The active install is the one equal to `active`,
 * never assumed to be the first: a tool without an active install can still list installs
 * that providers hold.
 */
export function otherInstalls(tool: Tool): Install[] {
  const { active } = tool;
  return active
    ? tool.installs.filter((install) => !sameInstall(install, active))
    : tool.installs;
}

export function isActive(tool: Tool, install: Install): boolean {
  return tool.active !== null && sameInstall(install, tool.active);
}

/** Path and source identify an install: the same file can be reported by PATH and a provider. */
function sameInstall(a: Install, b: Install): boolean {
  return a.path === b.path && a.source === b.source;
}
