"use client";

import { ChevronsUpDown, LogOut, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { Badge, Dot, Menu, type BadgeTone } from "@/components/ui";
import { useSession } from "@/context/session-context";
import { NAV_ITEMS, SETTINGS_ITEM, navItemForPath, type NavItem } from "@/lib/navigation";
import { clearSession, DEV_USERS, writeSession } from "@/lib/session";

import { Logo } from "./logo";
import { SearchIcon } from "./nav-icons";

/**
 * Rail (Paper · 00 Shell template): 232px, surface background, logo row,
 * search, nav, engine status, settings, account. The same content fills
 * the phone drawer.
 */
export function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { me, health } = useSession();
  const active = navItemForPath(pathname);

  /* ⌘K / Ctrl+K opens parts search in the library. */
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        router.push("/library");
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [router]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface px-2.5 pt-3.5 pb-3">
      <div className="flex items-center gap-2 px-1.5 pt-0.5 pb-3.5">
        <Logo />
        {me ? <span className="ml-auto min-w-0 truncate text-xs text-muted-text">{me.tenant_name}</span> : null}
      </div>

      <Link
        href="/library"
        onClick={onNavigate}
        className="mb-3 flex h-8 shrink-0 items-center gap-2 rounded-md border border-line bg-bg px-2.5 text-sm text-muted-text transition-colors duration-fast hover:border-line-strong"
      >
        <SearchIcon width={14} height={14} className="text-muted" />
        Search parts…
        <kbd className="ml-auto font-[inherit] text-caption text-muted-text">⌘K</kbd>
      </Link>

      <nav aria-label="Primary" className="flex flex-col gap-px">
        {NAV_ITEMS.map((item) => (
          <NavRow key={item.id} item={item} active={active?.id === item.id} onNavigate={onNavigate} />
        ))}
      </nav>

      <div className="min-h-4 flex-1" />

      <EngineStatus
        rows={[
          { tone: "pass", label: "Kernel · build123d local" },
          health
            ? health.llm_configured
              ? { tone: "pass", label: `Planner · ${health.llm_deployment ?? "online"}` }
              : { tone: health.planner === "disabled" ? "neutral" : "consent", label: health.planner === "disabled" ? "Planner · disabled" : "Planner · not configured" }
            : { tone: "neutral", label: "Planner · checking…" },
          health?.freecad_available
            ? { tone: "pass", label: "FreeCAD adapter · ready" }
            : { tone: "neutral", label: "FreeCAD adapter · not installed" },
        ]}
      />

      <NavRow item={SETTINGS_ITEM} active={active?.id === SETTINGS_ITEM.id} onNavigate={onNavigate} />

      <div className="mt-2 border-t border-line pt-2">
        <AccountMenu />
      </div>
    </div>
  );
}

function NavRow({ item, active, onNavigate }: { item: NavItem; active: boolean; onNavigate?: () => void }) {
  const Icon = item.icon;
  const row = "flex h-8 shrink-0 items-center gap-2.5 rounded-md px-2.5 text-sm";
  if (item.planned) {
    return (
      <span className={`${row} text-muted-text`} aria-disabled="true">
        <Icon className="text-muted" />
        {item.label}
        <Badge tone="consent" className="ml-auto py-0! text-caption!">
          Planned
        </Badge>
      </span>
    );
  }
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={`${row} transition-colors duration-fast ease-out ${active ? "bg-surface-2 font-semibold text-ink" : "text-ink hover:bg-surface-2"}`}
    >
      <Icon className={active ? "text-ink" : "text-body"} />
      {item.label}
    </Link>
  );
}

function EngineStatus({ rows }: { rows: { tone: BadgeTone; label: string }[] }) {
  return (
    <Link
      href="/system"
      aria-label="Engine status, open system status"
      className="mb-2.5 flex flex-col gap-1.5 rounded-panel border border-line bg-bg px-3 py-2.5 transition-colors duration-fast hover:border-line-strong"
    >
      {rows.map((r) => (
        <span key={r.label} className={`flex min-w-0 items-center gap-1.5 text-xs ${r.tone === "neutral" ? "text-muted-text" : "text-ink"}`}>
          <Dot tone={r.tone} />
          <span className="truncate">{r.label}</span>
        </span>
      ))}
    </Link>
  );
}

/** Account row (Paper avatar + name + role · org) opening the account menu. */
export function AccountMenu({ placement = "top-start" as const }: { placement?: "top-start" | "bottom-end" }) {
  const router = useRouter();
  const { me, refresh } = useSession();

  function switchTo(email: string) {
    writeSession(email);
    refresh();
    router.push("/projects");
    router.refresh();
  }

  return (
    <Menu
      label="Account"
      placement={placement}
      header={
        me ? (
          <div className="border-b border-line px-3.5 pt-1.5 pb-2.5">
            <p className="truncate text-sm font-semibold text-ink">{me.name}</p>
            <p className="truncate text-xs text-muted-text">{me.email}</p>
          </div>
        ) : null
      }
      items={[
        ...DEV_USERS.filter((u) => u.email !== me?.email).map((u) => ({
          id: u.email,
          label: `Switch to ${u.name}`,
          detail: "dev",
          icon: <UserRound size={14} strokeWidth={1.8} />,
          onSelect: () => switchTo(u.email),
        })),
        {
          id: "sign-out",
          label: "Sign out",
          icon: <LogOut size={14} strokeWidth={1.8} />,
          onSelect: () => {
            clearSession();
            router.replace("/login");
          },
        },
      ]}
      trigger={(p) => (
        <button
          {...p}
          type="button"
          aria-label={me ? `Account: ${me.name}` : "Account"}
          className="flex w-full min-w-0 items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors duration-fast hover:bg-surface-2"
        >
          <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-ai-text text-xs font-semibold text-white" aria-hidden>
            {me?.name.slice(0, 1) ?? "·"}
          </span>
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-sm text-ink">{me?.name ?? "Signed in"}</span>
            <span className="truncate text-caption text-muted-text">{me ? `${roleLabel(me.role)} · ${me.tenant_name}` : ""}</span>
          </span>
          <ChevronsUpDown size={14} strokeWidth={1.8} className="shrink-0 text-muted" aria-hidden />
        </button>
      )}
    />
  );
}

/** "org_admin" -> "Org admin" (sentence case, per the copy rules). */
function roleLabel(role: string) {
  const text = role.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
