"use client";

import { LogOut, Menu, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

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
        "flex h-full shrink-0 flex-col border-r border-line bg-bg",
        "transition-[width,transform] duration-base ease-out",
        "fixed inset-y-0 left-0 z-50 lg:relative lg:z-30 lg:translate-x-0",
        showExpanded ? "w-[252px]" : "w-[68px]",
        open ? "translate-x-0" : "-translate-x-full pointer-events-none lg:pointer-events-auto lg:translate-x-0",
      ].join(" ")}
    >
      <div className={["flex h-14 shrink-0 items-center border-b border-line", showExpanded ? "gap-2.5 px-4" : "justify-center"].join(" ")}>
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

      <div className={["flex shrink-0 flex-col gap-1.5 border-t border-line py-3", showExpanded ? "px-3" : "px-[14px]"].join(" ")}>
        <div className="hidden lg:contents">
          <SidebarItem
            icon={showExpanded ? PanelLeftClose : PanelLeftOpen}
            label={showExpanded ? "Collapse sidebar" : "Expand sidebar"}
            onClick={() => setExpanded((v) => !v)}
            expanded={showExpanded}
          />
        </div>
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
      className="flex size-8 items-center justify-center rounded-full bg-surface-2 text-muted outline-none transition-colors duration-base hover:bg-surface-2 hover:text-body lg:hidden"
    >
      <Menu size={16} strokeWidth={1.75} aria-hidden />
    </button>
  );
}
