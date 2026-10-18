/**
 * Shared surface primitives.
 *
 * From the Chronos design system (unchanged apart from the RCM-specific
 * PriorityBadge). Everything consumes semantic tokens only: no hex, no raw palette.
 */

import { Children, type ComponentPropsWithoutRef, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

/** Same chevron used for flow labels, status changes, and column moves. */
export function InlineArrow({ className = "" }: { className?: string }) {
  return (
    <ChevronRight
      size={12}
      strokeWidth={1.75}
      aria-hidden
      className={`inline-block shrink-0 ${className}`}
    />
  );
}

/** Native select with room between the chevron and the pill edge. */
export function Select({
  className = "",
  children,
  ...props
}: ComponentPropsWithoutRef<"select">) {
  const wide = className.includes("w-full");
  return (
    <span className={`relative inline-flex min-w-0 ${wide ? "w-full" : ""}`}>
      <select
        {...props}
        className={`appearance-none pr-8 pl-3 ${className}`.trim()}
      >
        {children}
      </select>
      <ChevronDown
        size={12}
        strokeWidth={1.75}
        aria-hidden
        className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-quaternary"
      />
    </span>
  );
}

// --- split row -------------------------------------------------------------

type SplitFrom = "md" | "lg" | "xl" | "2xl";
type SplitRatio = "1.4/1" | "1/1.4" | "1.6/1" | "1/2";

const SPLIT_DIR: Record<SplitFrom, string> = {
  md: "md:flex-row",
  lg: "lg:flex-row",
  xl: "xl:flex-row",
  "2xl": "2xl:flex-row",
};

const SPLIT_GROW: Record<SplitFrom, Record<SplitRatio, [string, string]>> = {
  md: {
    "1.4/1": ["md:flex-[1.4]", "md:flex-1"],
    "1/1.4": ["md:flex-1", "md:flex-[1.4]"],
    "1.6/1": ["md:flex-[1.6]", "md:flex-1"],
    "1/2": ["md:flex-1", "md:flex-[2]"],
  },
  lg: {
    "1.4/1": ["lg:flex-[1.4]", "lg:flex-1"],
    "1/1.4": ["lg:flex-1", "lg:flex-[1.4]"],
    "1.6/1": ["lg:flex-[1.6]", "lg:flex-1"],
    "1/2": ["lg:flex-1", "lg:flex-[2]"],
  },
  xl: {
    "1.4/1": ["xl:flex-[1.4]", "xl:flex-1"],
    "1/1.4": ["xl:flex-1", "xl:flex-[1.4]"],
    "1.6/1": ["xl:flex-[1.6]", "xl:flex-1"],
    "1/2": ["xl:flex-1", "xl:flex-[2]"],
  },
  "2xl": {
    "1.4/1": ["2xl:flex-[1.4]", "2xl:flex-1"],
    "1/1.4": ["2xl:flex-1", "2xl:flex-[1.4]"],
    "1.6/1": ["2xl:flex-[1.6]", "2xl:flex-1"],
    "1/2": ["2xl:flex-1", "2xl:flex-[2]"],
  },
};

/**
 * Two-up layout that stacks below `from`, then sits side by side.
 * Equal height comes from flex stretch, not height:100% on an auto row —
 * that circular size is what let charts paint over neighboring tables.
 */
export function SplitRow({
  children,
  from = "lg",
  ratio = "1.4/1",
  className = "",
}: {
  children: ReactNode;
  from?: SplitFrom;
  ratio?: SplitRatio;
  className?: string;
}) {
  const grow = SPLIT_GROW[from][ratio];
  return (
    <div className={`flex flex-col items-stretch gap-4 isolate ${SPLIT_DIR[from]} ${className}`}>
      {Children.map(children, (child, index) => (
        <div className={`flex min-h-0 min-w-0 flex-col overflow-hidden ${grow[index] ?? "lg:flex-1"}`}>
          {child}
        </div>
      ))}
    </div>
  );
}

// --- panel -----------------------------------------------------------------

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
    <section
      className={`isolate flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-muted bg-container ${className}`}
    >
      {title || action ? (
        <header className="flex h-11 shrink-0 items-center justify-between gap-3 border-b border-muted px-4">
          {title ? (
            <h2 className="min-w-0 truncate text-caption tracking-[0.08em] text-quaternary uppercase">
              {title}
            </h2>
          ) : (
            <span />
          )}
          {action ? <div className="min-w-0 shrink-0">{action}</div> : null}
        </header>
      ) : null}
      <div className={`flex min-h-0 min-w-0 flex-1 flex-col ${padded ? "overflow-auto p-4" : "overflow-hidden"}`}>
        {children}
      </div>
    </section>
  );
}

// --- KPI -------------------------------------------------------------------

export function KpiTile({
  label,
  value,
  delta,
  hint,
  mark,
  tone = "neutral",
}: {
  label: string;
  value: string;
  /** Signed percentage, pre-formatted, e.g. "+4.2%". */
  delta?: string;
  hint?: string;
  mark?: ReactNode;
  tone?: "neutral" | "success" | "info" | "warning" | "error";
}) {
  const deltaTone =
    tone === "success"
      ? "text-success"
      : tone === "info"
        ? "text-info"
        : tone === "warning"
          ? "text-warning"
          : tone === "error"
            ? "text-error"
            : "text-tertiary";

  return (
    <div className="flex min-w-0 flex-col gap-1.5 rounded-lg border border-muted bg-container px-4 py-3.5">
      <div className="flex items-start justify-between gap-2">
        <span className="truncate text-caption tracking-[0.08em] text-quaternary uppercase">
          {label}
        </span>
        {mark}
      </div>
      <span className="font-display text-display-xl tabular text-primary sm:text-display-2xl">
        {value}
      </span>
      <div className="flex items-baseline gap-2">
        {delta ? <span className={`text-body-sm tabular ${deltaTone}`}>{delta}</span> : null}
        {hint ? <span className="truncate text-caption text-quaternary">{hint}</span> : null}
      </div>
    </div>
  );
}

// --- status --------------------------------------------------------------

export type StatusTone = "success" | "info" | "neutral" | "warning" | "error";

const TONE_CLASS: Record<StatusTone, string> = {
  success: "bg-success-badge",
  info: "bg-info-badge",
  neutral: "bg-neutral-badge",
  warning: "bg-warning-badge",
  error: "bg-error-badge",
};

export function StatusBadge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: StatusTone;
}) {
  return (
    <span
      className={`inline-flex max-w-full items-center truncate rounded-full px-2.5 py-0.5 text-caption font-medium text-badge ${TONE_CLASS[tone]}`}
    >
      {children}
    </span>
  );
}

/** Small dot for dense rows where a full badge is too heavy. */
export function StatusDot({ tone = "neutral" }: { tone?: StatusTone }) {
  const bg: Record<StatusTone, string> = {
    success: "bg-success",
    info: "bg-info",
    neutral: "bg-neutral",
    warning: "bg-warning",
    error: "bg-error",
  };
  return <span className={`inline-block size-1.5 rounded-full ${bg[tone]}`} aria-hidden />;
}

// --- empty state -----------------------------------------------------------

export function EmptyState({
  title,
  detail,
  mark,
}: {
  title: string;
  detail?: string;
  mark?: ReactNode;
}) {
  return (
    <div className="flex h-full min-h-[160px] flex-col items-center justify-center gap-1.5 px-6 text-center">
      {mark}
      <p className="text-body-md text-tertiary">{title}</p>
      {detail ? <p className="text-body-sm text-quaternary">{detail}</p> : null}
    </div>
  );
}

// --- breakdown -------------------------------------------------------------

/**
 * Horizontal bar breakdown. Used for denials by root cause, by payer and by
 * code deliberately monochrome, since the categories carry no status meaning.
 */
export function BarList({
  rows,
  onSelect,
  selectedId,
  formatValue = (v) => v.toLocaleString("en-US"),
}: {
  rows: { id: string; label: string; value: number }[];
  onSelect?: (id: string) => void;
  selectedId?: string;
  formatValue?: (value: number) => string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));

  return (
    <ul className="flex flex-col gap-1.5">
      {rows.map((row) => {
        const selected = row.id === selectedId;
        const content = (
          <>
            <span className="flex items-baseline justify-between gap-3">
              <span className="truncate text-body-sm text-secondary">{row.label}</span>
              <span className="shrink-0 text-body-sm tabular text-primary">
                {formatValue(row.value)}
              </span>
            </span>
            <span className="mt-1 block h-1.5 w-full overflow-hidden rounded-full bg-raised-2">
              <span
                className={`block h-full rounded-full ${selected ? "bg-action-primary" : "bg-quaternary"}`}
                style={{ width: `${(row.value / max) * 100}%` }}
              />
            </span>
          </>
        );

        return (
          <li key={row.id}>
            {onSelect ? (
              <button
                type="button"
                onClick={() => onSelect(row.id)}
                aria-pressed={selected}
                className="block w-full rounded-md px-1.5 py-1 text-left transition-colors duration-[150ms] hover:bg-raised"
              >
                {content}
              </button>
            ) : (
              <div className="px-1.5 py-1">{content}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
