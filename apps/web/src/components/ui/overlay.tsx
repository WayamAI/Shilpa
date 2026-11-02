"use client";

import { X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

import { IconButton } from "./button";

const EDGE = 8; // never closer than this to a viewport edge

/* ---------------------------------------------------------------------------
   Positioning: below the anchor (or above when there is more room there),
   start-aligned, then clamped so the panel never leaves the viewport. Runs
   again on resize and on any scroll.
   ------------------------------------------------------------------------ */

export type Placement = "bottom-start" | "bottom-end" | "top-start" | "top-end";

/** Writes the panel position straight to its style: no re-render per scroll. */
export function useAnchoredPosition(
  open: boolean,
  anchor: RefObject<HTMLElement | null>,
  panel: RefObject<HTMLElement | null>,
  placement: Placement = "bottom-start",
  gap = 6,
) {
  useLayoutEffect(() => {
    if (!open) return;
    function update() {
      const a = anchor.current?.getBoundingClientRect();
      const p = panel.current;
      if (!a || !p) return;
      const vw = document.documentElement.clientWidth;
      const vh = window.innerHeight;
      p.style.setProperty("max-width", `${vw - EDGE * 2}px`);
      const width = Math.min(p.offsetWidth, vw - EDGE * 2);
      const height = p.scrollHeight;
      const below = vh - a.bottom - gap - EDGE;
      const above = a.top - gap - EDGE;
      const onTop = placement.startsWith("top") ? !(above < height && below > above) : below < height && above > below;
      const room = Math.max(120, onTop ? above : below);
      let left = placement.endsWith("end") ? a.right - width : a.left;
      left = Math.max(EDGE, Math.min(left, vw - width - EDGE));
      const top = onTop ? Math.max(EDGE, a.top - gap - Math.min(height, room)) : a.bottom + gap;
      p.style.setProperty("top", `${top}px`);
      p.style.setProperty("left", `${left}px`);
      p.style.setProperty("max-height", `${room}px`);
      p.style.setProperty("visibility", "visible");
    }
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, anchor, panel, placement, gap]);
}

/** Initial style for an anchored panel, before the first measurement. */
const HIDDEN: CSSProperties = { position: "fixed", top: 0, left: 0, visibility: "hidden" };

function useDismiss(open: boolean, onClose: () => void, refs: RefObject<HTMLElement | null>[]) {
  useEffect(() => {
    if (!open) return;
    function onPointer(event: PointerEvent) {
      if (refs.some((r) => r.current?.contains(event.target as Node))) return;
      onClose();
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose, refs]);
}

const noop = () => () => {};

/** Renders into body in the same pass on the client, nothing on the server. */
export function Portal({ children }: { children: ReactNode }) {
  const client = useSyncExternalStore(noop, () => true, () => false);
  return client ? createPortal(children, document.body) : null;
}

export const PANEL = "z-50 overflow-auto rounded-lg border border-line-strong bg-bg shadow-popover motion-safe:animate-[overlay-in_var(--duration-fast)_var(--ease-out)]";

/* ---------------------------------------------------------------------------
   Popover: a trigger plus a non-modal panel. Focus moves in on open and
   back to the trigger on close.
   ------------------------------------------------------------------------ */

export function Popover({
  trigger,
  label,
  children,
  placement = "bottom-start",
  className = "",
}: {
  trigger: (props: { ref: RefObject<HTMLButtonElement | null>; "aria-expanded": boolean; "aria-controls": string; onClick: () => void }) => ReactNode;
  label: string;
  children: ReactNode;
  placement?: Placement;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const anchor = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  useAnchoredPosition(open, anchor, panel, placement);
  const close = useCallback(() => {
    setOpen(false);
    anchor.current?.focus();
  }, []);
  const refs = useMemo(() => [anchor, panel], []);
  useDismiss(open, close, refs);

  useEffect(() => {
    if (open) panel.current?.focus();
  }, [open]);

  return (
    <>
      {trigger({ ref: anchor, "aria-expanded": open, "aria-controls": id, onClick: () => setOpen((v) => !v) })}
      {open ? (
        <Portal>
          <div ref={panel} id={id} role="dialog" aria-label={label} tabIndex={-1} style={HIDDEN} className={`${PANEL} p-3 ${className}`}>
            {children}
          </div>
        </Portal>
      ) : null}
    </>
  );
}

/* ---------------------------------------------------------------------------
   Menu: role=menu with arrow keys, Home/End, type-ahead free.
   ------------------------------------------------------------------------ */

export type MenuItem = { id: string; label: ReactNode; icon?: ReactNode; detail?: ReactNode; danger?: boolean; disabled?: boolean; onSelect: () => void };

export function Menu({
  trigger,
  label,
  items,
  header,
  placement = "bottom-start",
  className = "",
}: {
  trigger: (props: { ref: RefObject<HTMLButtonElement | null>; "aria-expanded": boolean; "aria-haspopup": "menu"; "aria-controls": string; onClick: () => void; onKeyDown: (e: ReactKeyboardEvent) => void }) => ReactNode;
  label: string;
  items: MenuItem[];
  header?: ReactNode;
  placement?: Placement;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const anchor = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  useAnchoredPosition(open, anchor, panel, placement);
  const close = useCallback(() => {
    setOpen(false);
    anchor.current?.focus();
  }, []);
  const refs = useMemo(() => [anchor, panel], []);
  useDismiss(open, close, refs);

  const focusItem = (index: number) => {
    const els = Array.from(panel.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not([disabled])') ?? []);
    if (!els.length) return;
    els[(index + els.length) % els.length].focus();
  };

  useEffect(() => {
    if (open) requestAnimationFrame(() => focusItem(0));
  }, [open]);

  function onPanelKey(event: ReactKeyboardEvent) {
    const els = Array.from(panel.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not([disabled])') ?? []);
    const at = els.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "ArrowDown") focusItem(at + 1);
    else if (event.key === "ArrowUp") focusItem(at - 1);
    else if (event.key === "Home") focusItem(0);
    else if (event.key === "End") focusItem(els.length - 1);
    else if (event.key === "Tab") setOpen(false);
    else return;
    event.preventDefault();
  }

  return (
    <>
      {trigger({
        ref: anchor,
        "aria-expanded": open,
        "aria-haspopup": "menu",
        "aria-controls": id,
        onClick: () => setOpen((v) => !v),
        onKeyDown: (e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            setOpen(true);
          }
        },
      })}
      {open ? (
        <Portal>
          <div ref={panel} style={HIDDEN} className={`${PANEL} min-w-[200px] py-1 ${className}`} onKeyDown={onPanelKey}>
            {header}
            <div id={id} role="menu" aria-label={label} className="flex flex-col px-1">
              {items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="menuitem"
                  disabled={item.disabled}
                  onClick={() => {
                    close();
                    item.onSelect();
                  }}
                  className={`flex h-8 min-w-0 items-center gap-2.5 rounded-sm px-2.5 text-left text-sm outline-none transition-colors duration-fast hover:bg-surface focus-visible:bg-surface focus-visible:shadow-none disabled:opacity-45 ${item.danger ? "text-fail-text" : "text-ink"}`}
                >
                  {item.icon ? <span className="flex size-4 shrink-0 items-center justify-center text-body">{item.icon}</span> : null}
                  <span className="min-w-0 flex-1 truncate">{item.label}</span>
                  {item.detail ? <span className="shrink-0 text-xs text-muted-text">{item.detail}</span> : null}
                </button>
              ))}
            </div>
          </div>
        </Portal>
      ) : null}
    </>
  );
}

/* ---------------------------------------------------------------------------
   Tooltip: on hover after a short delay and immediately on keyboard focus.
   Supplementary only: the trigger must already have an accessible name.
   ------------------------------------------------------------------------ */

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const anchor = useRef<HTMLSpanElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const timer = useRef<number | undefined>(undefined);
  useAnchoredPosition(open, anchor, panel, "top-start", 6);
  const show = (delay: number) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), delay);
  };
  const hide = () => {
    window.clearTimeout(timer.current);
    setOpen(false);
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && hide();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <span
      ref={anchor}
      className="inline-flex"
      aria-describedby={open ? id : undefined}
      onPointerEnter={() => show(400)}
      onPointerLeave={hide}
      onFocus={() => show(0)}
      onBlur={hide}
    >
      {children}
      {open ? (
        <Portal>
          <div
            ref={panel}
            id={id}
            role="tooltip"
            style={HIDDEN}
            className="pointer-events-none z-[60] max-w-[260px] rounded-sm bg-ink px-2 py-1 text-xs text-white"
          >
            {content}
          </div>
        </Portal>
      ) : null}
    </span>
  );
}

/* ---------------------------------------------------------------------------
   Modal shell shared by Dialog and Drawer: focus trap, Escape, scroll lock,
   focus returns to the opener.
   ------------------------------------------------------------------------ */

function useModal(panel: RefObject<HTMLElement | null>, onClose: () => void) {
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const first = panel.current?.querySelector<HTMLElement>("[data-autofocus]");
    (first ?? panel.current)?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panel.current) return;
      const focusable = Array.from(
        panel.current.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'),
      );
      if (!focusable.length) return;
      const firstEl = focusable[0];
      const lastEl = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === firstEl) {
        event.preventDefault();
        lastEl.focus();
      } else if (!event.shiftKey && document.activeElement === lastEl) {
        event.preventDefault();
        firstEl.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [panel, onClose]);
}

/** Paper · 09 Modals: 426px, 22px padding, 14px radius, image, title, body, actions right. */
export function Dialog({
  title,
  image,
  description,
  children,
  actions,
  onClose,
  size = "md",
}: {
  title: string;
  image?: string;
  description?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  onClose: () => void;
  /** md is the Paper modal; xl is for review work that needs room (drawing review). */
  size?: "md" | "xl";
}) {
  const id = useId();
  const descId = useId();
  const panel = useRef<HTMLDivElement>(null);
  useModal(panel, onClose);
  const xl = size === "xl";

  return (
    <Portal>
      <div
        className="fixed inset-0 z-50 flex items-end justify-center bg-stage/40 p-0 sm:items-center sm:p-6 motion-safe:animate-[fade-in_var(--duration-base)_var(--ease-out)]"
        onPointerDown={(e) => e.target === e.currentTarget && onClose()}
      >
        <div
          ref={panel}
          role="dialog"
          aria-modal="true"
          aria-labelledby={id}
          aria-describedby={description ? descId : undefined}
          tabIndex={-1}
          className={[
            "flex max-h-[calc(100dvh-24px)] w-full flex-col overflow-hidden rounded-t-xl bg-bg shadow-dialog outline-none sm:rounded-xl",
            "motion-safe:animate-[dialog-in_var(--duration-base)_var(--ease-out)]",
            xl ? "h-full sm:max-w-[1480px]" : "sm:max-w-[426px]",
          ].join(" ")}
        >
          {xl ? (
            <header className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-5 py-4">
              <div className="min-w-0">
                <h2 id={id} className="text-title">
                  {title}
                </h2>
                {description ? (
                  <div id={descId} className="mt-1 text-xs text-body">
                    {description}
                  </div>
                ) : null}
              </div>
              <IconButton label="Close" onClick={onClose}>
                <X size={16} strokeWidth={1.8} aria-hidden />
              </IconButton>
            </header>
          ) : null}
          <div className={`min-h-0 flex-1 ${xl ? "overflow-hidden" : "flex flex-col gap-3.5 overflow-auto p-5.5"}`}>
            {!xl ? (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element -- static decorative webp */}
                {image ? <img src={image} alt="" width={40} height={40} className="shrink-0" /> : null}
                <h2 id={id} className="text-title">
                  {title}
                </h2>
                {description ? (
                  <div id={descId} className="text-prose text-body">
                    {description}
                  </div>
                ) : null}
              </>
            ) : null}
            {children}
            {!xl && actions ? <div className="flex flex-wrap justify-end gap-2 pt-0.5">{actions}</div> : null}
          </div>
          {xl && actions ? <footer className="flex shrink-0 justify-end gap-2 border-t border-line px-5 py-3">{actions}</footer> : null}
        </div>
      </div>
    </Portal>
  );
}

/** Side sheet: from the left for navigation (Paper · Mobile), from the right for detail. */
export function Drawer({
  label,
  side = "right",
  onClose,
  children,
  className = "",
}: {
  label: string;
  side?: "left" | "right";
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useModal(panel, onClose);
  return (
    <Portal>
      <div
        className="fixed inset-0 z-50 bg-stage/40 motion-safe:animate-[fade-in_var(--duration-base)_var(--ease-out)]"
        onPointerDown={(e) => e.target === e.currentTarget && onClose()}
      >
        <div
          ref={panel}
          role="dialog"
          aria-modal="true"
          aria-label={label}
          tabIndex={-1}
          className={[
            "absolute inset-y-0 flex w-[min(320px,calc(100vw-48px))] flex-col overflow-auto bg-bg shadow-dialog outline-none",
            side === "left"
              ? "left-0 motion-safe:animate-[drawer-left_var(--duration-base)_var(--ease-out)]"
              : "right-0 motion-safe:animate-[drawer-right_var(--duration-base)_var(--ease-out)]",
            className,
          ].join(" ")}
        >
          {children}
        </div>
      </div>
    </Portal>
  );
}

/* ---------------------------------------------------------------------------
   Toast: polite live region, bottom right on desktop, full width on phones.
   Auto-dismiss after 5s unless it carries an action; hover pauses nothing
   because there is always a close button.
   ------------------------------------------------------------------------ */

type ToastTone = "neutral" | "pass" | "fail" | "consent";
type Toast = { id: number; title: string; detail?: string; tone: ToastTone; action?: { label: string; onClick: () => void } };
type ToastInput = Omit<Toast, "id" | "tone"> & { tone?: ToastTone };

const ToastContext = createContext<((t: ToastInput) => void) | null>(null);

const TOAST_BAR: Record<ToastTone, string> = {
  neutral: "bg-muted",
  pass: "bg-pass",
  fail: "bg-fail",
  consent: "bg-consent",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (t: ToastInput) => {
      const id = ++seq.current;
      setToasts((all) => [...all.slice(-2), { tone: "neutral", ...t, id }]);
      if (!t.action) window.setTimeout(() => dismiss(id), 5000);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        role="status"
        className="pointer-events-none fixed inset-x-4 bottom-4 z-[70] flex flex-col items-stretch gap-2 sm:right-6 sm:bottom-6 sm:left-auto sm:w-[360px]"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto flex items-start gap-3 overflow-hidden rounded-lg border border-line-strong bg-bg py-3 pr-2 pl-3 shadow-popover motion-safe:animate-[toast-in_var(--duration-base)_var(--ease-out)]"
          >
            <span aria-hidden className={`mt-0.5 h-4 w-1 shrink-0 rounded-full ${TOAST_BAR[t.tone]}`} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-ink">{t.title}</p>
              {t.detail ? <p className="mt-0.5 text-xs text-body">{t.detail}</p> : null}
              {t.action ? (
                <button
                  type="button"
                  onClick={() => {
                    t.action?.onClick();
                    dismiss(t.id);
                  }}
                  className="mt-1.5 rounded-sm text-sm font-semibold text-action-text hover:underline"
                >
                  {t.action.label}
                </button>
              ) : null}
            </div>
            <IconButton label="Dismiss" size="sm" onClick={() => dismiss(t.id)}>
              <X size={14} strokeWidth={1.8} aria-hidden />
            </IconButton>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const push = useContext(ToastContext);
  if (!push) throw new Error("useToast must be used within ToastProvider");
  return push;
}
