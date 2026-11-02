"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

type BaseProps = {
  icon: LucideIcon;
  /** Shown when the rail is expanded; always the aria-label when it is not. */
  label: string;
  active?: boolean;
  disabled?: boolean;
  /** Rail state. Collapsed renders a circular icon button only. */
  expanded?: boolean;
  /** Fired after a route link is followed used to close the mobile drawer. */
  onNavigate?: () => void;
};

type SidebarItemProps = BaseProps &
  (
    | { href: string; onClick?: never }
    | { href?: undefined; onClick?: () => void }
  );

function puckClass(active: boolean, disabled: boolean) {
  return [
    "flex size-9 shrink-0 items-center justify-center rounded-full",
    "transition-[background-color,color] duration-base ease-out",
    active
      ? "bg-action text-on-action"
      : "bg-surface-2 text-muted group-hover:bg-surface-2 group-hover:text-body",
    disabled ? "bg-surface text-muted" : "",
  ].join(" ");
}

/**
 * One navigation control. Renders as a link when given `href`, otherwise a
 * button, so utility controls and routes share the same visual treatment.
 */
export function SidebarItem({
  icon: Icon,
  label,
  active = false,
  disabled = false,
  expanded = false,
  href,
  onClick,
  onNavigate,
}: SidebarItemProps) {
  const wrapper = [
    "group relative flex items-center rounded-full outline-none",
    "transition-colors duration-base ease-out",
    "",
    expanded ? "w-full gap-3 pr-3" : "justify-center",
    disabled ? "pointer-events-none" : "",
  ].join(" ");

  const content = (
    <>
      <span className={puckClass(active, disabled)}>
        <Icon size={17} strokeWidth={1.75} aria-hidden />
      </span>
      {expanded ? (
        <span
          className={[
            "truncate text-xs font-semibold transition-colors duration-base",
            active ? "text-ink" : "text-muted-text group-hover:text-body",
          ].join(" ")}
        >
          {label}
        </span>
      ) : null}
    </>
  );

  if (href) {
    return (
      <Link
        href={href}
        title={expanded ? undefined : label}
        aria-label={label}
        aria-current={active ? "page" : undefined}
        onClick={onNavigate}
        className={wrapper}
      >
        {content}
      </Link>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={expanded ? undefined : label}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      className={wrapper}
    >
      {content}
    </button>
  );
}

/** Collapsible group header same puck language, plus a chevron when expanded. */
export function SidebarGroupTrigger({
  icon: Icon,
  label,
  active = false,
  expanded = false,
  open = false,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  active?: boolean;
  expanded?: boolean;
  open?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={expanded ? undefined : label}
      aria-label={label}
      aria-expanded={open}
      className={[
        "group relative flex items-center rounded-full outline-none",
        "transition-colors duration-base ease-out",
        "",
        expanded ? "w-full gap-3 pr-2" : "justify-center",
      ].join(" ")}
    >
      <span className={puckClass(active, false)}>
        <Icon size={17} strokeWidth={1.75} aria-hidden />
      </span>
      {expanded ? (
        <>
          <span
            className={[
              "min-w-0 flex-1 truncate text-left text-xs font-semibold transition-colors duration-base",
              active ? "text-ink" : "text-muted-text group-hover:text-body",
            ].join(" ")}
          >
            {label}
          </span>
          <ChevronRight
            size={14}
            strokeWidth={1.75}
            aria-hidden
            className={[
              "shrink-0 text-muted transition-transform duration-base",
              open ? "rotate-90" : "",
            ].join(" ")}
          />
        </>
      ) : null}
    </button>
  );
}

/** Nested leaf a short tick off the shared spine. The last leaf is an L. */
export function SidebarTreeItem({
  href,
  label,
  icon: Icon,
  active = false,
  last = false,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  active?: boolean;
  last?: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      onClick={onNavigate}
      className={[
        "group relative flex items-center gap-2 rounded-lg py-1.5 pr-2 pl-3",
        "outline-none transition-colors duration-base ease-out",
        "",
        active
          ? "bg-surface-2 text-ink"
          : "text-muted-text hover:bg-surface-2 hover:text-body",
      ].join(" ")}
    >
      {last ? (
        <span
          aria-hidden
          className="pointer-events-none absolute top-0 -left-px h-1/2 w-2.5 rounded-bl-[3px] border-b border-l border-line"
        />
      ) : (
        <span
          aria-hidden
          className="pointer-events-none absolute top-1/2 -left-px h-px w-2.5 bg-line"
        />
      )}
      <Icon
        size={14}
        strokeWidth={1.75}
        aria-hidden
        className={active ? "text-body" : "text-muted group-hover:text-muted"}
      />
      <span className="truncate text-xs font-semibold">{label}</span>
    </Link>
  );
}

export function SidebarTreeLabel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <p
      className={[
        "px-3 py-1 text-xs tracking-[0.08em] text-muted-text uppercase",
        className ?? "",
      ].join(" ")}
    >
      {children}
    </p>
  );
}

/** Spine stops at the last leaf so it cannot paint through groups below. */
export function SidebarTreeBranch({ children }: { children: ReactNode }) {
  return (
    <div className="relative mt-0.5 ml-[18px] overflow-hidden">
      <span
        aria-hidden
        className="pointer-events-none absolute top-0 bottom-4 left-0 w-px bg-line"
      />
      {children}
    </div>
  );
}
