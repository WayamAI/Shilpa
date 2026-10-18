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
    "bg-action-primary text-action-primary-content hover:bg-action-primary-hover disabled:bg-action-primary-disabled",
  secondary:
    "border border-muted bg-action text-secondary hover:border-default hover:bg-raised-2 hover:text-primary disabled:text-quaternary disabled:hover:bg-action",
  tertiary: "text-tertiary hover:bg-action-tertiary-hover hover:text-secondary disabled:text-quaternary",
};

const BUTTON_SIZE: Record<ButtonSize, string> = {
  md: "h-9 px-4 text-label-md gap-2",
  sm: "h-8 px-3 text-label-sm gap-1.5",
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
        "transition-colors duration-[180ms] focus-visible:ring-2 focus-visible:ring-active",
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
      className={`flex size-8 shrink-0 items-center justify-center rounded-full bg-action icon-tertiary outline-none transition-colors duration-[180ms] hover:bg-raised-2 hover:icon-secondary focus-visible:ring-2 focus-visible:ring-active disabled:opacity-50 ${className}`}
    >
      {children}
    </button>
  );
}

// --- fields -----------------------------------------------------------------

const FIELD =
  "w-full rounded-full border border-muted bg-action px-4 text-body-md text-primary outline-none placeholder:text-quaternary transition-colors duration-[180ms] focus-visible:border-default focus-visible:ring-2 focus-visible:ring-active disabled:text-tertiary";

/** Caption label above a control (Chronos sign-in pattern). */
export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5">
      <span className="text-caption tracking-[0.08em] text-quaternary uppercase">{label}</span>
      {children}
      {hint ? <span className="text-body-sm text-quaternary">{hint}</span> : null}
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
      className={`h-8 w-24 rounded-full border border-muted bg-action px-3 text-right text-body-sm tabular text-primary outline-none transition-colors duration-[180ms] focus-visible:border-default focus-visible:ring-2 focus-visible:ring-active disabled:bg-transparent disabled:text-secondary ${className}`}
    />
  );
}

export function Textarea({ className = "", ...props }: ComponentPropsWithoutRef<"textarea">) {
  return (
    <textarea
      {...props}
      className={`min-h-[84px] w-full resize-none rounded-2xl border border-muted bg-action px-4 py-3 text-body-md text-primary outline-none placeholder:text-quaternary transition-colors duration-[180ms] focus-visible:border-default focus-visible:ring-2 focus-visible:ring-active disabled:text-tertiary ${className}`}
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
    <div role="tablist" aria-label={label} className="flex min-w-0 gap-0.5 rounded-full border border-muted bg-action p-0.5">
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
              "h-7 min-w-0 flex-auto truncate rounded-full px-2 text-label-sm outline-none",
              "transition-colors duration-[180ms] focus-visible:ring-2 focus-visible:ring-active",
              selected ? "bg-action-primary text-action-primary-content" : "text-tertiary hover:bg-raised-2 hover:text-secondary",
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-3 sm:p-6">
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        tabIndex={-1}
        className={`flex max-h-full w-full flex-col overflow-hidden rounded-xl border border-muted bg-container shadow-lg outline-none ${size === "xl" ? "max-w-[1480px]" : "max-w-xl"}`}
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-muted px-5 py-4">
          <div className="min-w-0">
            <h2 id={id} className="font-display text-display-lg text-primary">
              {title}
            </h2>
            {subtitle ? <div className="mt-1 text-body-sm text-tertiary">{subtitle}</div> : null}
          </div>
          <IconButton label="Close" onClick={onClose}>
            <X size={16} strokeWidth={1.75} aria-hidden />
          </IconButton>
        </header>
        <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
        {footer ? <footer className="shrink-0 border-t border-muted px-5 py-3">{footer}</footer> : null}
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
        <div key={row.label} className="flex items-baseline justify-between gap-4 border-b border-muted py-2 last:border-b-0" title={row.title}>
          <dt className="text-body-sm text-tertiary">{row.label}</dt>
          <dd className="min-w-0 truncate text-right text-body-md tabular text-primary">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
