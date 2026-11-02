"use client";

import { Info } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/**
 * Compact “i” beside a page title. The long how-to copy lives here so it
 * does not eat a row of the page.
 */
export function InfoPopover({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative inline-flex shrink-0" ref={rootRef}>
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex size-7 items-center justify-center rounded-full text-muted-text outline-none transition-colors duration-[150ms] hover:bg-surface hover:text-body focus-visible:ring-2 focus-visible:ring-line-strong"
      >
        <Info size={15} strokeWidth={1.75} aria-hidden />
      </button>
      {open ? (
        <div
          id={id}
          role="dialog"
          aria-label={label}
          className="absolute top-[calc(100%+8px)] left-0 z-50 w-[min(calc(100vw-2.5rem),22rem)] rounded-lg border border-line bg-bg p-3 shadow-popover sm:w-[28rem]"
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}
