"use client";

/**
 * Controls Shilpa needs that Chronos composes inline. Same recipes as the
 * Chronos sign-in and top bar (pill shapes, 180ms colour transitions, the
 * active focus ring), packaged once. Semantic tokens only.
 */

import { X } from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from "react";

// --- button -----------------------------------------------------------------

type ButtonVariant = "primary" | "secondary" | "tertiary";
type ButtonSize = "md" | "sm";

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-action text-on-action hover:bg-action-hover disabled:bg-action/45",
  secondary:
    "border border-line bg-surface-2 text-body hover:border-line-strong hover:bg-surface-2 hover:text-ink disabled:text-muted-text disabled:hover:bg-surface-2",
  tertiary: "text-muted-text hover:bg-surface-2 hover:text-body disabled:text-muted-text",
};

const BUTTON_SIZE: Record<ButtonSize, string> = {
  md: "h-9 px-4 text-sm font-semibold gap-2",
  sm: "h-8 px-3 text-xs font-semibold gap-1.5",
};

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  children,
  ...props
}: ComponentPropsWithoutRef<"button"> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return (
    <button
      type="button"
      {...props}
      className={[
        "inline-flex shrink-0 items-center justify-center rounded-full outline-none",
        "transition-colors duration-[180ms] focus-visible:ring-2 focus-visible:ring-line-strong",
        "disabled:cursor-not-allowed",
        BUTTON_VARIANT[variant],
        BUTTON_SIZE[size],
        className,
      ].join(" ")}
    >
      {children}
    </button>
  );
}

/** Circular icon control, as used for theme and menu toggles in Chronos. */
export function IconButton({
  label,
  className = "",
  children,
  ...props
}: ComponentPropsWithoutRef<"button"> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      {...props}
      className={`flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-2 text-muted outline-none transition-colors duration-[180ms] hover:bg-surface-2 hover:text-body focus-visible:ring-2 focus-visible:ring-line-strong disabled:opacity-50 ${className}`}
    >
      {children}
    </button>
  );
}

// --- fields -----------------------------------------------------------------

const FIELD =
  "w-full rounded-full border border-line bg-surface-2 px-4 text-sm text-ink outline-none placeholder:text-muted-text transition-colors duration-[180ms] focus-visible:border-line-strong focus-visible:ring-2 focus-visible:ring-line-strong disabled:text-muted-text";

/** Caption label above a control (Chronos sign-in pattern). */
export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5">
      <span className="text-xs tracking-[0.08em] text-muted-text uppercase">{label}</span>
      {children}
      {hint ? <span className="text-xs text-muted-text">{hint}</span> : null}
    </label>
  );
}

export function TextInput({ className = "", ...props }: ComponentPropsWithoutRef<"input">) {
  return <input {...props} className={`h-11 ${FIELD} ${className}`} />;
}

/** Compact numeric input for dense parameter tables. */
export function NumberInput({ className = "", ...props }: ComponentPropsWithoutRef<"input">) {
  return (
    <input
      type="number"
      step="any"
      inputMode="decimal"
      {...props}
      className={`h-8 w-24 rounded-full border border-line bg-surface-2 px-3 text-right text-xs tabular text-ink outline-none transition-colors duration-[180ms] focus-visible:border-line-strong focus-visible:ring-2 focus-visible:ring-line-strong disabled:bg-transparent disabled:text-body ${className}`}
    />
  );
}

export function Textarea({ className = "", ...props }: ComponentPropsWithoutRef<"textarea">) {
  return (
    <textarea
      {...props}
      className={`min-h-[84px] w-full resize-none rounded-2xl border border-line bg-surface-2 px-4 py-3 text-sm text-ink outline-none placeholder:text-muted-text transition-colors duration-[180ms] focus-visible:border-line-strong focus-visible:ring-2 focus-visible:ring-line-strong disabled:text-muted-text ${className}`}
    />
  );
}

// --- tabs -------------------------------------------------------------------

/**
 * Segmented pill tabs. Equal-width segments always fit their container; the
 * selected segment takes the primary action surface, like the active filter
 * chip on the Chronos exception queue.
 */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex min-w-0 gap-0.5 rounded-full border border-line bg-surface-2 p-0.5">
      {tabs.map((tab) => {
        const selected = tab.id === value;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(tab.id)}
            className={[
              "h-7 min-w-0 flex-auto truncate rounded-full px-2 text-xs font-semibold outline-none",
              "transition-colors duration-[180ms] focus-visible:ring-2 focus-visible:ring-line-strong",
              selected ? "bg-action text-on-action" : "text-muted-text hover:bg-surface-2 hover:text-body",
            ].join(" ")}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

// --- dialog -----------------------------------------------------------------

/** Full-height modal sheet for review work that needs room (drawing review). */
export function Dialog({
  title,
  subtitle,
  onClose,
  children,
  footer,
  size = "xl",
}: {
  title: string;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: "md" | "xl";
}) {
  const id = useId();
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stage/50 p-3 sm:p-6">
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        tabIndex={-1}
        className={`flex max-h-full w-full flex-col overflow-hidden rounded-xl border border-line bg-bg shadow-popover outline-none ${size === "xl" ? "max-w-[1480px]" : "max-w-xl"}`}
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 id={id} className="text-lg font-semibold text-ink">
              {title}
            </h2>
            {subtitle ? <div className="mt-1 text-xs text-muted-text">{subtitle}</div> : null}
          </div>
          <IconButton label="Close" onClick={onClose}>
            <X size={16} strokeWidth={1.75} aria-hidden />
          </IconButton>
        </header>
        <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
        {footer ? <footer className="shrink-0 border-t border-line px-5 py-3">{footer}</footer> : null}
      </div>
    </div>
  );
}

// --- key/value list ----------------------------------------------------------

/** Label left, value right, as on the Chronos claim panel. */
export function KeyValue({ rows }: { rows: { label: string; value: ReactNode; title?: string }[] }) {
  return (
    <dl className="flex flex-col">
      {rows.map((row) => (
        <div key={row.label} className="flex items-baseline justify-between gap-4 border-b border-line py-2 last:border-b-0" title={row.title}>
          <dt className="text-xs text-muted-text">{row.label}</dt>
          <dd className="min-w-0 truncate text-right text-sm tabular text-ink">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
