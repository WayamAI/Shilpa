"use client";

import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Drawer } from "@/components/ui";
import { SessionProvider, useSession } from "@/context/session-context";

import { SidebarContent } from "./sidebar";
import { TabBar } from "./tab-bar";
import { MobileHeader, TopBar } from "./top-bar";

/** Sign-in is a full-bleed surface; everything else sits in the shell. */
export function ShellGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/login") return children;
  return (
    <SessionProvider>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}

/**
 * Desktop (lg+): 232px rail + 48px header. Phone and tablet: page-title
 * header, content, bottom tab bar; the full rail opens as a left drawer.
 */
function AppShell({ children }: { children: ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const { error } = useSession();

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-bg">
      <a
        href="#main"
        className="sr-only z-[80] rounded-md bg-ink px-3 py-2 text-sm text-white focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <aside aria-label="Sidebar" className="hidden w-[232px] shrink-0 border-r border-line lg:block">
        <SidebarContent />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <TopBar />
        <MobileHeader onMenu={() => setNavOpen(true)} />
        {error ? (
          <div role="alert" className="shrink-0 border-b border-fail/40 bg-fail-soft px-4 py-2 text-xs text-fail-text lg:px-6">
            The Shilpa API is not reachable ({error}). Start it with <code className="font-semibold">uv run python -m shilpa.dev</code>.
          </div>
        ) : null}
        <main id="main" tabIndex={-1} className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-bg outline-none">
          {children}
        </main>
        <TabBar />
      </div>

      {navOpen ? (
        <Drawer label="Navigation" side="left" onClose={() => setNavOpen(false)}>
          <SidebarContent onNavigate={() => setNavOpen(false)} />
        </Drawer>
      ) : null}
    </div>
  );
}
