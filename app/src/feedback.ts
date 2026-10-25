import { useCallback, useEffect, useState } from "react";

/** How long a confirmation or error stays on screen. */
const SHOWN_MS = 4000;

export interface Feedback {
  text: string;
  failed: boolean;
}

/**
 * The outcome of the last install action, shown in one place and cleared after a while. A
 * new report replaces the old one, so rapid actions never stack messages.
 */
export function useFeedback(): {
  feedback: Feedback | null;
  report: (outcome: Promise<unknown>, done: string) => void;
} {
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  useEffect(() => {
    if (!feedback) return;
    const timer = setTimeout(() => {
      setFeedback(null);
    }, SHOWN_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [feedback]);

  const report = useCallback((outcome: Promise<unknown>, done: string) => {
    outcome.then(
      () => {
        setFeedback({ text: done, failed: false });
      },
      (error: unknown) => {
        setFeedback({
          text: error instanceof Error ? error.message : String(error),
          failed: true,
        });
      },
    );
  }, []);

  return { feedback, report };
}

/**
 * Copies with the web clipboard API, so the webview needs no clipboard plugin or command.
 * If the webview refuses, the text is on screen to select by hand.
 */
export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Also reached when the clipboard API is missing altogether.
    throw new Error("Could not copy. Select the text instead.");
  }
}
