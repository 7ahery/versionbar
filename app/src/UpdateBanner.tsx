import { Download } from "lucide-react";
import { useState } from "react";

import { type UpdateState, useUpdate } from "@/shell";

/**
 * The app update on offer (spec story 69). Nothing is downloaded until the user clicks: the
 * click is the confirmation. Failed checks never reach this banner (DEV-10); only a failed
 * install does, with Retry. Shown above whatever the popup lists, which it never replaces.
 */
export function UpdateBanner() {
  const { update, install } = useUpdate();
  // The offer the user already confirmed, so a second click before the shell answers cannot
  // ask twice. Any new state from the shell is a new object and re-enables the buttons.
  const [confirmed, setConfirmed] = useState<UpdateState | null>(null);
  const waiting = update !== null && confirmed === update;

  if (!update?.version) return null;
  const version = update.version;
  const confirm = () => {
    if (waiting) return;
    setConfirmed(update);
    install();
  };

  return (
    <div className="flex flex-col items-center gap-2 border-b border-border px-4 py-2 text-center text-xs">
      {update.installing ? (
        <p aria-live="polite" className="text-muted-foreground">
          Installing v{version}…
        </p>
      ) : update.error ? (
        <>
          <p className="text-destructive">{update.error}</p>
          <button
            type="button"
            onClick={confirm}
            disabled={waiting}
            className="rounded-md border border-border px-2 py-1 font-medium hover:bg-accent disabled:opacity-50"
          >
            Retry update
          </button>
        </>
      ) : (
        <button
          type="button"
          onClick={confirm}
          disabled={waiting}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-medium hover:bg-accent disabled:opacity-50"
        >
          <Download className="size-3.5" aria-hidden />
          Update to v{version} → Install & restart
        </button>
      )}
    </div>
  );
}
