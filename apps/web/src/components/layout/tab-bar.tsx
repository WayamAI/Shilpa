"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { TAB_ITEMS, navItemForPath } from "@/lib/navigation";

/**
 * Phone tab bar (Paper · 03 Mobile): three slots, 22px glyph over an 11px
 * label, active in action orange. Planned slots (none today) are visible but inert.
 * Inactive labels use muted-text: Paper's muted is 3.24:1 at 11px.
 */
export function TabBar() {
  const active = navItemForPath(usePathname());
  return (
    <nav
      aria-label="Primary"
      className="flex shrink-0 justify-around border-t border-line bg-bg px-3 pt-2.5 pb-[max(12px,env(safe-area-inset-bottom))] lg:hidden"
    >
      {TAB_ITEMS.map((item) => {
        const Icon = item.icon;
        const on = active?.id === item.id;
        const body = (
          <>
            <Icon width={22} height={22} />
            <span className={`text-caption ${on ? "font-semibold" : ""}`}>{item.label}</span>
          </>
        );
        const slot = "flex min-w-16 flex-col items-center gap-[3px] rounded-md px-2 py-0.5";
        return item.planned ? (
          <span key={item.id} aria-disabled="true" title={`${item.label} (planned)`} className={`${slot} text-muted-text opacity-60`}>
            {body}
          </span>
        ) : (
          <Link
            key={item.id}
            href={item.href}
            aria-current={on ? "page" : undefined}
            className={`${slot} transition-colors duration-fast ${on ? "text-action-text" : "text-muted-text hover:text-ink"}`}
          >
            {body}
          </Link>
        );
      })}
    </nav>
  );
}
