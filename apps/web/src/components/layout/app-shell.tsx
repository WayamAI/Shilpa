"use client";

import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { SessionProvider, useSession } from "@/context/session-context";

import { Sidebar } from "./sidebar";
import { TopBar } from "./top-bar";

/** Sign-in is a full-bleed surface; everything else sits in the studio chrome. */
export function ShellGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/login") return children;
  return (
    <SessionProvider>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}

function AppShell({ children }: { children: ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const { error } = useSession();

  return (
    <div className="flex h-screen w-full overflow-hidden bg-surface">
      {navOpen ? (
        <button type="button" aria-label="Close navigation" onClick={() => setNavOpen(false)} className="fixed inset-0 z-40 bg-stage/50 lg:hidden" />
      ) : null}
      <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <TopBar onMenu={() => setNavOpen(true)} />
        {error ? (
          <div role="alert" className="shrink-0 border-b border-fail/40 bg-fail-soft px-5 py-2 text-xs text-fail-text">
            The Shilpa API is not reachable ({error}). Start it with <code className="font-medium">uv run python -m shilpa.dev</code>.
          </div>
        ) : null}
        <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-surface">{children}</main>
      </div>
    </div>
  );
}
