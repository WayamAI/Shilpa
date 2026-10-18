"use client";

import { LogOut, Menu, Moon, PanelLeftClose, PanelLeftOpen, SunMedium } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { useTheme } from "@/context/theme-context";
import { NAV_ITEMS, navItemForPath } from "@/lib/navigation";
import { clearSession } from "@/lib/session";

import { Logo } from "./logo";
import { SidebarItem } from "./sidebar-item";

/**
 * Primary navigation (Chronos rail). Collapsed: 68px icon pucks. Expanded or
 * mobile drawer: 252px with labels. Shilpa's few destinations need no tree.
 */
export function Sidebar({ open = false, onClose }: { open?: boolean; onClose?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const [expanded, setExpanded] = useState(false);
  const { isDark, toggleTheme } = useTheme();
  const active = navItemForPath(pathname);
  const showExpanded = expanded || open;

  function signOut() {
    clearSession();
    router.replace("/login");
  }

  return (
    <aside
      aria-label="Primary"
      data-expanded={showExpanded}
      className={[
        "flex h-full shrink-0 flex-col border-r border-muted bg-container",
        "transition-[width,transform] duration-200 ease-out",
        "fixed inset-y-0 left-0 z-50 lg:relative lg:z-30 lg:translate-x-0",
        showExpanded ? "w-[252px]" : "w-[68px]",
        open ? "translate-x-0" : "-translate-x-full pointer-events-none lg:pointer-events-auto lg:translate-x-0",
      ].join(" ")}
    >
      <div className={["flex h-14 shrink-0 items-center border-b border-muted", showExpanded ? "gap-2.5 px-4" : "justify-center"].join(" ")}>
        <Logo wordmark={showExpanded} />
      </div>

      <nav aria-label="Main navigation" className={["min-h-0 flex-1 py-3", showExpanded ? "overflow-y-auto px-3" : "px-[14px]"].join(" ")}>
        <ul className="flex flex-col gap-1.5">
          {NAV_ITEMS.map((item) => (
            <li key={item.href}>
              <SidebarItem
                icon={item.icon}
                label={item.label}
                href={item.href}
                active={active?.href === item.href}
                expanded={showExpanded}
                onNavigate={onClose}
              />
            </li>
          ))}
        </ul>
      </nav>

      <div className={["flex shrink-0 flex-col gap-1.5 border-t border-muted py-3", showExpanded ? "px-3" : "px-[14px]"].join(" ")}>
        <div className="hidden lg:contents">
          <SidebarItem
            icon={showExpanded ? PanelLeftClose : PanelLeftOpen}
            label={showExpanded ? "Collapse sidebar" : "Expand sidebar"}
            onClick={() => setExpanded((v) => !v)}
            expanded={showExpanded}
          />
        </div>
        <SidebarItem icon={isDark ? SunMedium : Moon} label={isDark ? "Switch to light" : "Switch to dark"} onClick={toggleTheme} expanded={showExpanded} />
        <SidebarItem icon={LogOut} label="Sign out" onClick={signOut} expanded={showExpanded} />
      </div>
    </aside>
  );
}

/** Mobile-only control lives in the top bar, not the rail. */
export function SidebarMenuButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Open navigation"
      className="flex size-8 items-center justify-center rounded-full bg-action icon-tertiary outline-none transition-colors duration-[180ms] hover:bg-raised-2 hover:icon-secondary focus-visible:ring-2 focus-visible:ring-active lg:hidden"
    >
      <Menu size={16} strokeWidth={1.75} aria-hidden />
    </button>
  );
}
