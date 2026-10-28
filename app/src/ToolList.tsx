import {
  ChevronRight,
  ClipboardCopy,
  Copy,
  FolderOpen,
  Search,
} from "lucide-react";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";

import { copyText, useFeedback } from "@/feedback";
import { cn } from "@/lib/utils";
import { openContainingFolder } from "@/shell";
import {
  type Arrangement,
  type Change,
  type Install,
  isActive,
  otherInstalls,
  type Tool,
  useToolRows,
} from "@/tools";

/** Search, the tool rows, and the missing tools in their own section at the bottom. */
export function ToolList({
  tools,
  previous,
  arrangement,
}: {
  tools: Tool[];
  /** The previous successful scan's tools, or null when there is none to compare with. */
  previous: Tool[] | null;
  arrangement: Arrangement;
}) {
  const [query, setQuery] = useState("");
  const [showMissing, setShowMissing] = useState(false);
  const { listed, missing, changes } = useToolRows(
    tools,
    previous,
    arrangement,
    query,
  );
  const searching = query.trim() !== "";
  // A search looks through missing tools too: hiding them must not make a search come up
  // empty for a tool that is listed, just not installed.
  const missingShown = searching || showMissing;
  const { feedback, report } = useFeedback();
  const searchRef = useRef<HTMLInputElement>(null);
  // The popup window is hidden, not closed, so the component stays mounted and `autoFocus`
  // only fires once. Each reopen focuses the window, which is when typing should start.
  useEffect(() => {
    const focusSearch = () => searchRef.current?.focus();
    window.addEventListener("focus", focusSearch);
    return () => {
      window.removeEventListener("focus", focusSearch);
    };
  }, []);
  return (
    <>
      <div className="relative border-b border-border px-3 py-2">
        <Search
          className="pointer-events-none absolute top-1/2 left-5 size-3.5 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <input
          type="search"
          aria-label="Search tools"
          placeholder="Search tools"
          value={query}
          ref={searchRef}
          // The popup opens to find a tool, so typing should start at once.
          autoFocus
          onChange={(event) => {
            setQuery(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") setQuery("");
          }}
          className="w-full rounded-md border border-border bg-transparent py-1 pr-2 pl-7 text-sm placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {listed.length > 0 && (
          <ul aria-label="Tools" className="divide-y divide-border">
            {listed.map((tool) => (
              <ToolRow
                key={tool.id}
                tool={tool}
                change={changes.get(tool.id)}
                report={report}
              />
            ))}
          </ul>
        )}
        {searching && listed.length === 0 && missing.length === 0 && (
          <p className="px-4 py-6 text-center text-sm text-muted-foreground">
            No tools match “{query.trim()}”.
          </p>
        )}
        {missing.length > 0 && (
          <MissingSection
            tools={missing}
            changes={changes}
            searching={searching}
            shown={missingShown}
            onToggle={() => {
              setShowMissing((was) => !was);
            }}
            report={report}
          />
        )}
      </div>
      {/* Always rendered, so screen readers announce each new message. */}
      <p
        role="status"
        className={cn(
          "border-t border-border px-4 py-1.5 text-xs empty:hidden",
          feedback?.failed ? "text-destructive" : "text-muted-foreground",
        )}
      >
        {feedback?.text}
      </p>
    </>
  );
}

type Report = ReturnType<typeof useFeedback>["report"];

/** Greyed out at the bottom; behind a toggle unless a search is looking for them. */
function MissingSection({
  tools,
  changes,
  searching,
  shown,
  onToggle,
  report,
}: {
  tools: Tool[];
  changes: ReadonlyMap<string, Change>;
  searching: boolean;
  shown: boolean;
  onToggle: () => void;
  report: Report;
}) {
  return (
    <section className="border-t border-border">
      {searching ? (
        <h2 className="px-4 py-2 text-xs text-muted-foreground">Not found</h2>
      ) : (
        <button
          type="button"
          aria-expanded={shown}
          onClick={onToggle}
          className="w-full px-4 py-2 text-left text-xs text-muted-foreground hover:bg-accent focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
        >
          {shown ? "Hide" : "Show"} not found ({tools.length})
        </button>
      )}
      {shown && (
        <ul
          aria-label="Not found"
          className="divide-y divide-border opacity-60"
        >
          {tools.map((tool) => (
            <ToolRow
              key={tool.id}
              tool={tool}
              change={changes.get(tool.id)}
              report={report}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function ToolRow({
  tool,
  change,
  report,
}: {
  tool: Tool;
  change: Change | undefined;
  report: Report;
}) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const others = otherInstalls(tool).length;
  const status = statusDisplay(tool);
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={detailsId}
        onClick={() => {
          setOpen((was) => !was);
        }}
        className="flex w-full items-baseline gap-2 px-4 py-2 text-left text-sm hover:bg-accent focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
      >
        <ChevronRight
          className={cn(
            "size-3.5 shrink-0 self-center text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
          aria-hidden
        />
        <span data-tool-name className="font-medium">
          {tool.name}
        </span>
        {others > 0 && (
          <span className="shrink-0 rounded-full bg-muted px-1.5 text-xs text-muted-foreground">
            +{others} install{others === 1 ? "" : "s"}
          </span>
        )}
        {change && change.kind !== "changed" && (
          <span className="shrink-0 rounded-full bg-accent px-1.5 text-xs text-accent-foreground">
            {changeLabel(change)}
          </span>
        )}
        <span
          className={cn(
            "ml-auto truncate tabular-nums",
            tool.active ? "text-muted-foreground" : status.colour,
            change?.kind === "changed" && "font-medium text-foreground",
          )}
        >
          {change?.kind === "changed"
            ? `${change.from} → ${change.to}`
            : tool.active
              ? tool.active.version
              : status.label}
        </span>
      </button>
      {open && <ToolDetails id={detailsId} tool={tool} report={report} />}
    </li>
  );
}

function ToolDetails({
  id,
  tool,
  report,
}: {
  id: string;
  tool: Tool;
  report: Report;
}) {
  return (
    <div id={id} className="space-y-2 px-4 pb-3 pl-9 text-xs">
      {tool.notes.length > 0 && (
        <ul className="space-y-1 text-muted-foreground">
          {tool.notes.map((note, index) => (
            // Notes can repeat and have no id; their order never changes within one scan.
            <li
              key={index}
              className="break-words whitespace-pre-wrap select-text"
            >
              {note}
            </li>
          ))}
        </ul>
      )}
      {tool.installs.length > 0 && (
        <ul className="space-y-2">
          {tool.installs.map((install) => (
            <InstallItem
              key={`${install.source}:${install.path}`}
              install={install}
              active={isActive(tool, install)}
              report={report}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function InstallItem({
  install,
  active,
  report,
}: {
  install: Install;
  active: boolean;
  report: Report;
}) {
  return (
    <li className="space-y-0.5">
      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-medium tabular-nums select-text">
          {install.version}
        </span>
        {active && <span className="text-foreground">Active</span>}
        <span className="text-muted-foreground">
          {sourceLabel(install.source)}
        </span>
        {install.via && (
          <span className="text-muted-foreground">via {install.via}</span>
        )}
      </p>
      <div className="flex items-start gap-1">
        <p className="min-w-0 flex-1 font-mono break-all text-muted-foreground select-text">
          {install.path}
        </p>
        <IconButton
          label="Copy version"
          onClick={() => {
            report(copyText(install.version), "Version copied");
          }}
        >
          <Copy className="size-3.5" aria-hidden />
        </IconButton>
        <IconButton
          label="Copy path"
          onClick={() => {
            report(copyText(install.path), "Path copied");
          }}
        >
          <ClipboardCopy className="size-3.5" aria-hidden />
        </IconButton>
        <IconButton
          label="Open containing folder"
          onClick={() => {
            report(openContainingFolder(install.path), "Opened in Explorer");
          }}
        >
          <FolderOpen className="size-3.5" aria-hidden />
        </IconButton>
      </div>
    </li>
  );
}

/** Icon-only, so the name doubles as the tooltip. */
function IconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
    >
      {children}
    </button>
  );
}

/**
 * The badge for a change that has no version pair to show. "Was" is the previous scan's
 * version, the only history there is; recovery is never worded as an upgrade.
 */
function changeLabel(change: Exclude<Change, { kind: "changed" }>): string {
  switch (change.kind) {
    case "found":
      return "Newly found";
    case "recovered":
      return "Recovered";
    case "missing":
      return change.from
        ? `Newly missing (was ${change.from})`
        : "Newly missing";
    case "failing":
      return change.from
        ? `Newly failing (was ${change.from})`
        : "Newly failing";
  }
}

/** `path`, or a provider id shown as-is, so providers added later need no UI change. */
function sourceLabel(source: string): string {
  return source === "path" ? "On PATH" : `From ${source}`;
}

/**
 * What to show for a tool with no active install. Failures stand out from a tool that is
 * simply not installed. The status is shown as-is for values added after this build
 * (schema/README.md).
 */
function statusDisplay(tool: Tool): { label: string; colour: string } {
  switch (tool.status as string) {
    case "missing":
      return { label: "Not found", colour: "text-muted-foreground" };
    case "error":
      return { label: "Error", colour: "text-destructive" };
    case "timeout":
      return { label: "Timed out", colour: "text-destructive" };
    default:
      return { label: tool.status, colour: "text-muted-foreground" };
  }
}
