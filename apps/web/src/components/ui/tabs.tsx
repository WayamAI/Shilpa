"use client";

import { useRef, type KeyboardEvent, type ReactNode } from "react";

type TabItem<T extends string> = { id: T; label: string; count?: number };

function useRovingKeys<T extends string>(tabs: TabItem<T>[], value: T, onChange: (id: T) => void) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  return {
    refs,
    onKeyDown(event: KeyboardEvent) {
      const at = tabs.findIndex((t) => t.id === value);
      let next = -1;
      if (event.key === "ArrowRight") next = (at + 1) % tabs.length;
      else if (event.key === "ArrowLeft") next = (at - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      if (next < 0) return;
      event.preventDefault();
      onChange(tabs[next].id);
      refs.current[next]?.focus();
    },
  };
}

/**
 * Underline tabs (Paper · Part detail inspector): 44px row, 18px gap,
 * selected is ink semibold with a 2px ink rule. Scrolls sideways on
 * narrow screens instead of wrapping.
 */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
  idPrefix,
  inset = true,
  className = "",
}: {
  tabs: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  label: string;
  /** Pairs each tab with a panel id `${idPrefix}-panel-${id}`. */
  idPrefix?: string;
  /** 20px side padding at a panel edge; off when the parent already pads. */
  inset?: boolean;
  className?: string;
}) {
  const { refs, onKeyDown } = useRovingKeys(tabs, value, onChange);
  return (
    <div
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={`flex h-11 min-w-0 shrink-0 items-end gap-4.5 overflow-x-auto border-b border-line [scrollbar-width:none] ${inset ? "px-5" : ""} ${className}`}
    >
      {tabs.map((tab, i) => {
        const selected = tab.id === value;
        return (
          <button
            key={tab.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={idPrefix ? `${idPrefix}-tab-${tab.id}` : undefined}
            aria-controls={idPrefix ? `${idPrefix}-panel-${tab.id}` : undefined}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            className={[
              "-mb-px shrink-0 rounded-t-sm border-b-2 pb-2.5 text-sm whitespace-nowrap transition-colors duration-fast ease-out",
              selected ? "border-ink font-semibold text-ink" : "border-transparent text-body hover:text-ink",
            ].join(" ")}
          >
            {tab.label}
            {tab.count !== undefined ? <span className="ml-1 tabular">{tab.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

/** Panel paired with a Tabs tab via idPrefix. */
export function TabPanel({ idPrefix, id, children, className = "" }: { idPrefix: string; id: string; children: ReactNode; className?: string }) {
  return (
    <div role="tabpanel" id={`${idPrefix}-panel-${id}`} aria-labelledby={`${idPrefix}-tab-${id}`} className={className}>
      {children}
    </div>
  );
}

/** Segmented control (Paper · viewport toolbar): white tray, 3px inset, selected on surface-2. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
  className = "",
}: {
  options: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  label: string;
  className?: string;
}) {
  const { refs, onKeyDown } = useRovingKeys(options, value, onChange);
  return (
    <div
      role="radiogroup"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={`inline-flex min-w-0 gap-0.5 rounded-md border border-line bg-bg p-[3px] shadow-toolbar ${className}`}
    >
      {options.map((o, i) => {
        const selected = o.id === value;
        return (
          <button
            key={o.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(o.id)}
            className={[
              "min-w-0 truncate rounded-sm px-2.5 py-[5px] text-xs transition-colors duration-fast ease-out",
              selected ? "bg-surface-2 font-semibold text-ink" : "text-body hover:text-ink",
            ].join(" ")}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
