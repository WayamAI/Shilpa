"use client";

import type { ReactNode } from "react";

import { Tabs, Tooltip } from "@/components/ui";

/**
 * Shared studio chrome, taken from Paper · 03 Part detail (5L-0) and the
 * mobile viewer (2FN-0): a bordered viewport with a toolbar tray, quiet
 * captions on the stage, and an inspector with underline tabs and
 * 14px section headings.
 */

/** Viewport frame: 12px radius, 1px line, stage colour from the viewer token. */
export function Viewport({
  label,
  className = "",
  children,
}: {
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      aria-label={label}
      className={`viewer-surface relative flex min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-line lg:rounded-lg ${className}`}
    >
      {children}
    </section>
  );
}

/** Toolbar tray (Paper): white, 1px line, 8px radius, 3px padding, 2px gap. */
export function ViewportToolbar({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div
      role="toolbar"
      aria-label={label}
      className={`flex max-w-full gap-0.5 overflow-x-auto rounded-md border border-line bg-bg p-[3px] shadow-toolbar [scrollbar-width:none] ${className}`}
    >
      {children}
    </div>
  );
}

/**
 * Toolbar item. `active` is a pressed toggle (surface-2, semibold ink),
 * `planned` shows a disabled item with a tooltip because it has no backend.
 */
export function ToolbarButton({
  children,
  active,
  planned,
  disabled,
  onClick,
  label,
}: {
  children: ReactNode;
  active?: boolean;
  planned?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  label?: string;
}) {
  const button = (
    <button
      type="button"
      aria-pressed={active === undefined ? undefined : active}
      aria-label={label}
      disabled={disabled || planned}
      onClick={onClick}
      className={[
        "shrink-0 rounded-sm px-2.5 py-[5px] text-xs whitespace-nowrap transition-colors duration-fast ease-out disabled:cursor-not-allowed",
        active ? "bg-surface-2 font-semibold text-ink" : "text-body hover:text-ink disabled:hover:text-body",
        planned || disabled ? "opacity-60" : "",
      ].join(" ")}
    >
      {children}
    </button>
  );
  return planned ? <Tooltip content="Planned">{button}</Tooltip> : button;
}

/** Quiet 12px caption lines over the stage (Paper: muted bottom-left, body bottom-right). */
export function ViewportCaption({ hint, facts, className = "" }: { hint?: ReactNode; facts?: ReactNode; className?: string }) {
  return (
    <div className={`pointer-events-none absolute right-3 bottom-3 left-3 flex flex-wrap items-end gap-x-3 gap-y-0.5 text-xs ${className}`}>
      {facts ? <span className="tabular text-body">{facts}</span> : null}
      {hint ? <span className="text-muted-text">{hint}</span> : null}
    </div>
  );
}

/** Inspector column: tabs on top, 20px side padding, scrolls on its own from lg up. */
export function Inspector<T extends string>({
  label,
  tabs,
  value,
  onChange,
  children,
  className = "",
  side = true,
}: {
  label: string;
  side?: boolean;
  tabs: { id: T; label: string; count?: number }[];
  value: T;
  onChange: (id: T) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <aside aria-label={label} className={`flex min-h-0 min-w-0 flex-col border-line ${side ? "lg:border-l" : ""} ${className}`}>
      <Tabs<T> label={`${label} sections`} value={value} onChange={onChange} tabs={tabs} idPrefix="inspector" />
      <div className="min-h-0 flex-1 px-4 py-4 lg:overflow-y-auto lg:px-5">{children}</div>
    </aside>
  );
}

/** Section heading (Paper: 14px semibold ink) with an optional count and trailing action. */
export function Section({
  title,
  count,
  action,
  children,
  className = "",
}: {
  title: string;
  count?: number | string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`flex min-w-0 flex-col gap-2 ${className}`}>
      <div className="flex min-h-7 items-center justify-between gap-3">
        <h3 className="min-w-0 truncate text-md">
          {title}
          {count !== undefined ? <span className="ml-1.5 font-normal text-body tabular">{count}</span> : null}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}

/** Small summary tiles under the mobile viewport (Paper M2: surface, 10px radius). */
export function Facts({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="flex gap-2">
      {items.map((i) => (
        <div key={i.label} className="flex min-w-0 flex-1 flex-col gap-0.5 rounded-panel bg-surface p-2.5">
          <dt className="text-caption text-body">{i.label}</dt>
          <dd className="truncate text-md font-semibold tabular text-ink">{i.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Table header cell class (Paper: 12px semibold body, 28px row) and the
 * 36px row used by the feature and checks tables.
 */
export const TH = "py-1.5 pr-2 text-left text-xs font-semibold text-body";

/**
 * Workspace body (Paper 03 Part detail on desktop, M2 on phone). Desktop: a
 * centre column (viewport, then the request thread) beside the inspector.
 * Phone: viewport, facts, inspector, then the thread, in that order. The
 * parent must be a column flex on phone and a two-column grid from lg up.
 */
export function WorkspaceLayout({
  viewport,
  facts,
  inspector,
  footer,
}: {
  viewport: ReactNode;
  facts?: ReactNode;
  inspector: ReactNode;
  footer: ReactNode;
}) {
  return (
    <>
      <div className="contents lg:flex lg:min-h-0 lg:min-w-0 lg:flex-col lg:gap-3 lg:overflow-y-auto lg:py-4 lg:pr-5 lg:pl-8">
        <div className="order-1 mx-4 mt-3 flex min-h-0 flex-col gap-3 lg:order-none lg:mx-0 lg:mt-0 lg:min-h-[320px] lg:flex-1">{viewport}</div>
        {facts ? <div className="order-2 mx-4 lg:hidden">{facts}</div> : null}
        <div className="order-4 mx-4 mb-4 flex min-h-[420px] flex-col lg:order-none lg:mx-0 lg:mb-0 lg:h-[360px] lg:min-h-[300px] lg:shrink-0">{footer}</div>
      </div>
      <div className="order-3 flex min-h-0 min-w-0 flex-col lg:order-none lg:overflow-hidden">{inspector}</div>
    </>
  );
}
