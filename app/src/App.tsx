import { getVersion } from "@tauri-apps/api/app";
import { Layers, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import type { ScanResult } from "schema";

import { cn } from "@/lib/utils";
import { PRODUCT_NAME } from "@/product";
import { FailedScreen, MissingUvScreen, SettingUpScreen } from "@/Recovery";
import { type Outcome, type ShellState, useShellState } from "@/shell";

type Tool = ScanResult["tools"][number];

export default function App() {
  const version = useShellVersion();
  const { state, refresh } = useShellState();
  const scanning = state?.scanning ?? false;

  return (
    <main className="flex h-screen flex-col bg-background text-foreground select-none">
      <header className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Layers className="size-4 text-muted-foreground" aria-hidden />
        <h1 className="text-sm font-semibold">{PRODUCT_NAME}</h1>
        {version && (
          <span className="text-xs text-muted-foreground">v{version}</span>
        )}
        <button
          type="button"
          onClick={refresh}
          disabled={scanning}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium hover:bg-accent disabled:opacity-50"
        >
          <RefreshCw
            className={cn("size-3.5", scanning && "animate-spin")}
            aria-hidden
          />
          Refresh
        </button>
      </header>
      {state?.current ? (
        <>
          <StatusLine state={state} />
          <ToolList tools={state.current.tools} />
        </>
      ) : (
        <NoResults state={state} onRetry={refresh} />
      )}
    </main>
  );
}

/**
 * What fills the popup while there is nothing to list: the first run's setup, or the recovery
 * screen for the last outcome. With results on screen, problems stay a line in the status
 * bar instead (see `describeProblem`), so a failed refresh never hides good data.
 */
function NoResults({
  state,
  onRetry,
}: {
  state: ShellState | null;
  onRetry: () => void;
}) {
  const scanning = state?.scanning ?? false;
  const outcome = state?.outcome;
  if (scanning && state?.setting_up) return <SettingUpScreen />;
  // Unknown kinds fall through to the plain empty state.
  if (outcome?.kind === "uv_missing") {
    return <MissingUvScreen scanning={scanning} onRetry={onRetry} />;
  }
  if (outcome?.kind === "failed") {
    return (
      <FailedScreen outcome={outcome} scanning={scanning} onRetry={onRetry} />
    );
  }
  return (
    <>
      <StatusLine state={state} />
      <p className="m-auto text-sm text-muted-foreground">
        {scanning ? null : "No scan results yet."}
      </p>
    </>
  );
}

/** Freshness, progress and the latest failure, above whatever results there are. */
function StatusLine({ state }: { state: ShellState | null }) {
  const scannedAt = state?.current?.scanned_at ?? null;
  const age = useAge(scannedAt);
  const problem = state?.outcome ? describeProblem(state.outcome) : null;

  return (
    <div className="space-y-1 border-b border-border px-4 py-2 text-xs text-muted-foreground">
      <p aria-live="polite">{state?.scanning ? "Scanning…" : age}</p>
      {problem && <p className="text-destructive">{problem}</p>}
    </div>
  );
}

/** A failure to mention, or null when the last attempt is fine or of a kind we don't know. */
function describeProblem(outcome: Outcome): string | null {
  switch (outcome.kind) {
    case "failed":
      return outcome.message ?? "The last scan failed.";
    case "uv_missing":
      return "uv was not found, so no scan could run.";
    default:
      return null;
  }
}

function ToolList({ tools }: { tools: Tool[] }) {
  return (
    <ul className="flex-1 divide-y divide-border overflow-y-auto">
      {tools.map((tool) => (
        <li
          key={tool.id}
          className="flex items-baseline justify-between gap-4 px-4 py-2 text-sm"
        >
          <span className="font-medium">{tool.name}</span>
          <span className="truncate text-muted-foreground tabular-nums">
            {activeLabel(tool)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function activeLabel(tool: Tool): string {
  if (tool.active) return tool.active.version;
  // The status is shown as-is for values added after this build (schema/README.md).
  switch (tool.status as string) {
    case "missing":
      return "Not found";
    case "error":
      return "Error";
    case "timeout":
      return "Timed out";
    default:
      return tool.status;
  }
}

const MINUTE = 60_000;

/** "Scanned 3 min ago", kept current while the popup stays open. */
function useAge(scannedAt: string | null): string | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 30_000);
    return () => {
      clearInterval(timer);
    };
  }, []);
  if (!scannedAt) return null;
  const at = Date.parse(scannedAt);
  if (Number.isNaN(at)) return null;
  // A scan newer than the last tick (or a clock skew) reads as "just now", not negative.
  const minutes = Math.floor(Math.max(0, now - at) / MINUTE);
  if (minutes < 1) return "Scanned just now";
  if (minutes < 60) return `Scanned ${String(minutes)} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `Scanned ${String(hours)} h ago`;
  return `Scanned ${String(Math.floor(hours / 24))} d ago`;
}

/** The version comes from the shell so it can never drift from the installed build. */
function useShellVersion(): string | null {
  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    getVersion().then(
      (v) => {
        if (current) setVersion(v);
      },
      // Purely informational: a missing version must never break the popup.
      () => {},
    );
    return () => {
      current = false;
    };
  }, []);
  return version;
}
