"use client";

import { Menu as MenuIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useNeedsYou } from "@/components/home/use-needs-you";
import { IconButton } from "@/components/ui";
import { navItemForPath } from "@/lib/navigation";

import { Mark } from "./logo";
import { NeedsYouIcon } from "./nav-icons";

const DISCLAIMER = "Geometry validated · not reviewed for engineering release";

/**
 * Desktop header (Paper · 00 Shell template): 48px, breadcrumb left,
 * the release disclaimer and the Needs-you bell right.
 */
export function TopBar({ title }: { title?: string }) {
  const pathname = usePathname();
  const label = title ?? navItemForPath(pathname)?.label ?? "Shilpa";
  return (
    <header className="hidden h-12 shrink-0 items-center gap-3 border-b border-line bg-bg px-6 lg:flex">
      <span className="min-w-0 truncate text-sm text-body">{label}</span>
      <span className="flex-1" />
      <span className="shrink-0 text-xs text-muted-text">{DISCLAIMER}</span>
      <NeedsYouBell />
    </header>
  );
}

/**
 * Phone header (Paper · 03 Mobile): mark, 24px page title, then the menu
 * button that opens the navigation drawer. The disclaimer moves under the
 * title so it stays visible.
 */
export function MobileHeader({ onMenu, title }: { onMenu: () => void; title?: string }) {
  const pathname = usePathname();
  const label = title ?? navItemForPath(pathname)?.label ?? "Shilpa";
  return (
    <header className="flex shrink-0 flex-col gap-1 bg-bg px-4 pt-3 pb-2 lg:hidden">
      <div className="flex items-center gap-2">
        <Mark size={26} />
        <span className="min-w-0 flex-1 truncate text-page font-semibold text-ink">{label}</span>
        <IconButton label="Open navigation" onClick={onMenu}>
          <MenuIcon size={18} strokeWidth={1.8} aria-hidden />
        </IconButton>
      </div>
      <p className="text-caption text-muted-text">{DISCLAIMER}</p>
    </header>
  );
}

/** Link to the Needs you inbox, with a count badge when something is waiting. Refetches on navigation. */
function NeedsYouBell() {
  const pathname = usePathname();
  const state = useNeedsYou(0, pathname);
  const count = state.status === "ready" ? state.items.length : 0;
  return (
    <Link
      href="/needs-you"
      aria-label={count > 0 ? `Needs you, ${count} waiting` : "Needs you"}
      className="relative inline-flex size-8.5 shrink-0 items-center justify-center rounded-md text-muted transition-colors duration-fast hover:bg-surface-2 hover:text-ink"
    >
      <NeedsYouIcon />
      {count > 0 ? (
        <span
          aria-hidden
          className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-action px-1 text-caption font-semibold text-on-action tabular"
        >
          {count > 99 ? "99+" : count}
        </span>
      ) : null}
    </Link>
  );
}
