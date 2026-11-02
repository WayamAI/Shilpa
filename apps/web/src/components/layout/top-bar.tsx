"use client";

import { usePathname } from "next/navigation";

import { StatusDot } from "@/components/ui/primitives";
import { useSession } from "@/context/session-context";
import { navItemForPath } from "@/lib/navigation";

import { SidebarMenuButton } from "./sidebar";

/** Where you are, whether the planner is online, and who is signed in. */
export function TopBar({ onMenu, title }: { onMenu?: () => void; title?: string }) {
  const pathname = usePathname();
  const { me, health } = useSession();
  const item = navItemForPath(pathname);
  const disabled = health?.planner === "disabled";

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line bg-surface px-4 sm:gap-4 sm:px-5">
      <div className="flex min-w-0 items-center gap-2.5">
        {onMenu ? <SidebarMenuButton onClick={onMenu} /> : null}
        {item ? (
          <span className="hidden text-xs tracking-[0.08em] text-muted-text uppercase sm:inline">{item.group}</span>
        ) : null}
        <h1 className="truncate text-lg font-semibold text-ink">{title ?? item?.label ?? "Shilpa"}</h1>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {health ? (
          <span
            className="hidden h-8 items-center gap-2 rounded-full border border-line bg-surface-2 px-3 text-xs font-semibold text-muted-text sm:flex"
            title={disabled ? "Azure OpenAI planner (disabled with SHILPA_LLM=off)" : "Azure OpenAI planner"}
          >
            <StatusDot tone={health.llm_configured ? "success" : disabled ? "neutral" : "warning"} />
            Planner
            <span className="text-muted-text">·</span>
            <span className={health.llm_configured ? "text-pass-text" : disabled ? "text-muted-text" : "text-consent-text"}>
              {health.llm_configured ? "Online" : disabled ? "Disabled" : "Not configured"}
            </span>
          </span>
        ) : null}
        {me ? (
          <span className="flex h-8 min-w-0 items-center gap-2 rounded-full border border-line bg-surface-2 py-1 pr-3 pl-1" title={`${me.email} · ${me.role}`}>
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-action text-xs text-on-action">
              {me.name.slice(0, 1)}
            </span>
            <span className="hidden min-w-0 flex-col leading-none md:flex">
              <span className="truncate text-xs font-semibold text-body">{me.name}</span>
              <span className="truncate text-[11px] text-muted-text">{me.tenant_name}</span>
            </span>
          </span>
        ) : null}
      </div>
    </header>
  );
}
