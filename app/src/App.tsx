import { getVersion } from "@tauri-apps/api/app";
import { Layers } from "lucide-react";
import { useEffect, useState } from "react";

import { PRODUCT_NAME } from "@/product";

export default function App() {
  const version = useShellVersion();

  return (
    <main className="flex h-screen flex-col bg-background text-foreground select-none">
      <header className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Layers className="size-4 text-muted-foreground" aria-hidden />
        <h1 className="text-sm font-semibold">{PRODUCT_NAME}</h1>
        {version && (
          <span className="ml-auto text-xs text-muted-foreground">
            v{version}
          </span>
        )}
      </header>
      <p className="m-auto text-sm text-muted-foreground">
        Tool versions will appear here.
      </p>
    </main>
  );
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
