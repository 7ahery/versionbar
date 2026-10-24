import { Loader2 } from "lucide-react";
import { type ReactNode, useState } from "react";

import { type Outcome, openUvDocs } from "@/shell";

/**
 * The screens shown instead of the tool list when there are no results to show: the first
 * run's setup, uv missing, and a failed scan. VersionBar installs nothing itself; the only
 * things it offers are text to copy, a link to uv's own instructions and Retry.
 */

/** The install command we suggest. Copied by the user and run in their own terminal. */
export const UV_INSTALL_COMMAND = "winget install astral-sh.uv";

/** How many of uv's last stderr lines the failure screen shows; Copy error has them all. */
const STDERR_LINES_SHOWN = 12;

const DOWNLOAD_NOTE =
  "uv may download Python and packages for VersionBar's own environment. VersionBar itself installs nothing.";

export function SettingUpScreen() {
  return (
    <Screen>
      <Loader2
        className="size-6 animate-spin text-muted-foreground"
        aria-hidden
      />
      <h2 className="text-sm font-semibold">Preparing environment</h2>
      <p className="text-xs text-muted-foreground" aria-live="polite">
        The first scan sets up VersionBar&apos;s own Python environment, which
        can take a few minutes. This happens once.
      </p>
      <p className="text-xs text-muted-foreground">{DOWNLOAD_NOTE}</p>
    </Screen>
  );
}

export function MissingUvScreen({
  scanning,
  onRetry,
}: {
  scanning: boolean;
  onRetry: () => void;
}) {
  return (
    <Screen>
      <h2 className="text-sm font-semibold">uv was not found</h2>
      <p className="text-xs text-muted-foreground">
        VersionBar uses uv to run its scanner. VersionBar does not install uv
        for you. Run this in a terminal, then press Retry:
      </p>
      <code className="block w-full rounded-md bg-muted px-3 py-2 text-left font-mono text-xs select-text">
        {UV_INSTALL_COMMAND}
      </code>
      <div className="flex flex-wrap justify-center gap-2">
        <CopyButton label="Copy command" text={UV_INSTALL_COMMAND} />
        <ActionButton onClick={openUvDocs}>
          Open the uv install guide
        </ActionButton>
        <RetryButton scanning={scanning} onRetry={onRetry} />
      </div>
    </Screen>
  );
}

export function FailedScreen({
  outcome,
  scanning,
  onRetry,
}: {
  outcome: Outcome;
  scanning: boolean;
  onRetry: () => void;
}) {
  const message = outcome.message ?? "The scan failed.";
  const stderr = outcome.stderr?.trim() ?? "";
  const shown = stderr.split("\n").slice(-STDERR_LINES_SHOWN).join("\n");
  // The whole error, so a bug report has what the screen had to cut.
  const report = stderr ? `${message}\n\n${stderr}` : message;

  return (
    <Screen>
      <h2 className="text-sm font-semibold">The scan failed</h2>
      <p className="text-xs text-destructive">{message}</p>
      {stderr && (
        <pre
          aria-label="Error output"
          className="max-h-40 w-full overflow-auto rounded-md bg-muted px-3 py-2 text-left font-mono text-xs whitespace-pre-wrap select-text"
        >
          {shown}
        </pre>
      )}
      <p className="text-xs text-muted-foreground">{DOWNLOAD_NOTE}</p>
      <div className="flex flex-wrap justify-center gap-2">
        <CopyButton label="Copy error" text={report} />
        <RetryButton scanning={scanning} onRetry={onRetry} />
      </div>
    </Screen>
  );
}

function Screen({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
      {children}
    </div>
  );
}

function RetryButton({
  scanning,
  onRetry,
}: {
  scanning: boolean;
  onRetry: () => void;
}) {
  return (
    <ActionButton onClick={onRetry} disabled={scanning}>
      {scanning ? "Retrying…" : "Retry"}
    </ActionButton>
  );
}

function ActionButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-md border border-border px-2.5 py-1 text-xs font-medium hover:bg-accent disabled:opacity-50"
    >
      {children}
    </button>
  );
}

/**
 * Copies with the web clipboard API, so the webview needs no clipboard plugin. If the
 * webview refuses, the text is already on screen to select by hand.
 */
function CopyButton({ label, text }: { label: string; text: string }) {
  const [result, setResult] = useState<"copied" | "failed" | null>(null);
  const copy = () => {
    // Inside `then` so a missing clipboard API, which throws, fails like a refused copy.
    Promise.resolve()
      .then(() => navigator.clipboard.writeText(text))
      .then(
        () => {
          setResult("copied");
        },
        () => {
          setResult("failed");
        },
      );
  };
  return (
    <>
      <ActionButton onClick={copy}>{label}</ActionButton>
      {result === "copied" && (
        <span
          role="status"
          className="self-center text-xs text-muted-foreground"
        >
          Copied
        </span>
      )}
      {result === "failed" && (
        <span role="status" className="self-center text-xs text-destructive">
          Could not copy. Select the text instead.
        </span>
      )}
    </>
  );
}
