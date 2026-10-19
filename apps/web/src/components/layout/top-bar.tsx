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
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-muted bg-page px-4 sm:gap-4 sm:px-5">
      <div className="flex min-w-0 items-center gap-2.5">
        {onMenu ? <SidebarMenuButton onClick={onMenu} /> : null}
        {item ? (
          <span className="hidden text-caption tracking-[0.08em] text-quaternary uppercase sm:inline">{item.group}</span>
        ) : null}
        <h1 className="truncate font-display text-display-lg text-primary">{title ?? item?.label ?? "Shilpa"}</h1>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {health ? (
          <span
            className="hidden h-8 items-center gap-2 rounded-full border border-muted bg-action px-3 text-label-sm text-tertiary sm:flex"
            title={disabled ? "Azure OpenAI planner (disabled with SHILPA_LLM=off)" : "Azure OpenAI planner"}
          >
            <StatusDot tone={health.llm_configured ? "success" : disabled ? "neutral" : "warning"} />
            Planner
            <span className="text-quaternary">·</span>
            <span className={health.llm_configured ? "text-success" : disabled ? "text-tertiary" : "text-warning"}>
              {health.llm_configured ? "Online" : disabled ? "Disabled" : "Not configured"}
            </span>
          </span>
        ) : null}
        {me ? (
          <span className="flex h-8 min-w-0 items-center gap-2 rounded-full border border-muted bg-action py-1 pr-3 pl-1" title={`${me.email} · ${me.role}`}>
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-action-primary text-caption text-action-primary-content">
              {me.name.slice(0, 1)}
            </span>
            <span className="hidden min-w-0 flex-col leading-none md:flex">
              <span className="truncate text-label-sm text-secondary">{me.name}</span>
              <span className="truncate text-[11px] text-quaternary">{me.tenant_name}</span>
            </span>
          </span>
        ) : null}
      </div>
    </header>
  );
}
