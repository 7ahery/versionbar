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
 * The rows to show for a search: the tools whose name or id contains `query` (ignoring case
 * and surrounding spaces), split into the main list and the missing section.
 */
export function useToolRows(
  tools: Tool[],
  query: string,
): { listed: Tool[]; missing: Tool[] } {
  return useMemo(() => {
    const needle = query.trim().toLowerCase();
    const found = needle
      ? tools.filter(
          (tool) =>
            tool.name.toLowerCase().includes(needle) ||
            tool.id.toLowerCase().includes(needle),
        )
      : tools;
    return splitMissing(found);
  }, [tools, query]);
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
