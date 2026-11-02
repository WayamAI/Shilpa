"use client";

import { Info } from "lucide-react";
import { Children, type ComponentPropsWithoutRef, type ReactNode } from "react";

import { Popover } from "./overlay";

/**
 * Surfaces. Paper cards carry no shadow: a 1px line and a 12px radius.
 * Interactive cards get a line-strong border on hover and the focus ring.
 */

export function Card({
  interactive = false,
  className = "",
  children,
  ...props
}: ComponentPropsWithoutRef<"div"> & { interactive?: boolean }) {
  return (
    <div
      {...props}
      className={`flex min-w-0 flex-col overflow-hidden rounded-lg border border-line bg-bg ${interactive ? "transition-colors duration-fast ease-out hover:border-line-strong" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

/** Titled panel: 16px semibold ink title (Paper section heading), action on the right. */
export function Panel({
  title,
  action,
  children,
  className = "",
  padded = true,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={`isolate flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-line bg-bg ${className}`}>
      {title || action ? (
        <header className="flex h-11 shrink-0 items-center justify-between gap-3 border-b border-line px-4">
          {title ? <h2 className="min-w-0 truncate text-md">{title}</h2> : <span />}
          {action ? <div className="min-w-0 shrink-0">{action}</div> : null}
        </header>
      ) : null}
      <div className={`flex min-h-0 min-w-0 flex-1 flex-col ${padded ? "overflow-auto p-4" : "overflow-hidden"}`}>{children}</div>
    </section>
  );
}

/** Label left, value right (numbers right-aligned, tabular). */
export function KeyValue({ rows }: { rows: { label: string; value: ReactNode; title?: string }[] }) {
  return (
    <dl className="flex flex-col">
      {rows.map((row) => (
        <div key={row.label} className="flex items-baseline justify-between gap-4 border-b border-line py-2 last:border-b-0" title={row.title}>
          <dt className="text-xs text-body">{row.label}</dt>
          <dd className="min-w-0 truncate text-right text-sm tabular text-ink">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Two columns from lg up, stacked below. Equal heights come from flex stretch. */
export function SplitRow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`flex flex-col items-stretch gap-4 lg:flex-row ${className}`}>
      {Children.map(children, (child, index) => (
        <div className={`flex min-h-0 min-w-0 flex-col ${index === 0 ? "lg:flex-[1.4]" : "lg:flex-1"}`}>{child}</div>
      ))}
    </div>
  );
}

/** Metric tile: label, value, optional hint. Sentence-case label. */
export function Metric({ label, value, hint, image }: { label: string; value: ReactNode; hint?: ReactNode; image?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-lg border border-line bg-bg px-4 py-3.5">
      <span className="flex min-w-0 items-start justify-between gap-2">
        <span className="truncate text-xs text-body">{label}</span>
        {/* eslint-disable-next-line @next/next/no-img-element -- decorative category icon */}
        {image ? <img src={image} alt="" width={28} height={28} className="-mt-1 -mr-1 size-7 shrink-0" /> : null}
      </span>
      <span className="text-2xl font-semibold tabular text-ink">{value}</span>
      {hint ? <span className="truncate text-xs text-muted-text">{hint}</span> : null}
    </div>
  );
}

/** "i" beside a title: long how-to copy lives in a popover, not on the page. */
export function InfoPopover({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Popover
      label={label}
      className="w-[min(calc(100vw-16px),420px)]"
      trigger={(p) => (
        <button
          {...p}
          type="button"
          aria-label={label}
          className="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted transition-colors duration-fast hover:bg-surface-2 hover:text-ink"
        >
          <Info size={15} strokeWidth={1.8} aria-hidden />
        </button>
      )}
    >
      {children}
    </Popover>
  );
}
