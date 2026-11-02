"use client";

import { Check, ChevronDown } from "lucide-react";
import {
  Children,
  isValidElement,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
  type CSSProperties,
  type ReactNode,
} from "react";

import { FIELD_BASE } from "./field";
import { PANEL, Portal, useAnchoredPosition } from "./overlay";

/**
 * Custom select (Paper · library toolbar "Source: All ▾"). Follows the
 * ARIA select-only combobox pattern: a button with role=combobox owns a
 * listbox. Focus stays on the button; the active option is announced via
 * aria-activedescendant.
 *
 * Keys: Enter, Space, ↓ or ↑ open; ↑ ↓ Home End move; typing jumps to the
 * first match; Enter or Space picks; Escape or Tab closes.
 *
 * It takes the same <option> and <optgroup> children as a native select
 * and calls onChange with { target: { value } }, so call sites read
 * e.target.value as before. A hidden input carries `name` for forms.
 */

type Opt = { value: string; label: string; disabled: boolean; group: string | null };

type OptionProps = { value?: string | number; disabled?: boolean; children?: ReactNode };
type GroupProps = { label?: string; children?: ReactNode };

function text(node: ReactNode): string {
  return Children.toArray(node)
    .map((c) => (typeof c === "string" || typeof c === "number" ? String(c) : isValidElement<{ children?: ReactNode }>(c) ? text(c.props.children) : ""))
    .join("");
}

function collect(children: ReactNode, group: string | null = null, out: Opt[] = []): Opt[] {
  Children.forEach(children, (child) => {
    if (!isValidElement(child)) return;
    if (child.type === "option") {
      const p = (child as ReactElement<OptionProps>).props;
      const label = text(p.children);
      out.push({ value: p.value === undefined ? label : String(p.value), label, disabled: !!p.disabled, group });
    } else if (child.type === "optgroup") {
      const p = (child as ReactElement<GroupProps>).props;
      collect(p.children, p.label ?? null, out);
    } else {
      collect((child as ReactElement<{ children?: ReactNode }>).props.children, group, out);
    }
  });
  return out;
}

const HIDDEN: CSSProperties = { position: "fixed", top: 0, left: 0, visibility: "hidden" };

export type SelectChange = { target: { value: string; name?: string } };

export function Select({
  value: controlled,
  defaultValue,
  onChange,
  children,
  size = "md",
  name,
  id,
  disabled = false,
  className = "",
  placeholder = "Select…",
  "aria-label": ariaLabel,
  "aria-describedby": describedBy,
  "aria-invalid": invalid,
}: {
  value?: string;
  defaultValue?: string;
  onChange?: (event: SelectChange) => void;
  children: ReactNode;
  size?: "md" | "sm";
  name?: string;
  id?: string;
  disabled?: boolean;
  className?: string;
  placeholder?: string;
  "aria-label"?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
}) {
  const options = useMemo(() => collect(children), [children]);
  const [own, setOwn] = useState(defaultValue ?? options.find((o) => !o.disabled)?.value ?? "");
  const value = controlled ?? own;
  const selectedIndex = options.findIndex((o) => o.value === value);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const typed = useRef({ text: "", at: 0 });
  const listId = useId();
  const autoId = useId();
  const optId = (i: number) => `${listId}-o${i}`;

  /* The list is at least as wide as its button. Runs before positioning. */
  useLayoutEffect(() => {
    if (open && button.current && panel.current) panel.current.style.setProperty("min-width", `${button.current.offsetWidth}px`);
  }, [open]);
  useAnchoredPosition(open, button, panel, "bottom-start", 4);

  useEffect(() => {
    if (!open) return;
    function onPointer(event: PointerEvent) {
      const t = event.target as Node;
      if (!button.current?.contains(t) && !panel.current?.contains(t)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open]);

  useEffect(() => {
    if (open) document.getElementById(optId(active))?.scrollIntoView({ block: "nearest" });
  });

  function enabledFrom(start: number, step: 1 | -1) {
    for (let i = start; i >= 0 && i < options.length; i += step) if (!options[i].disabled) return i;
    return -1;
  }

  function show(at = selectedIndex) {
    if (disabled || !options.length) return;
    setActive(at >= 0 && !options[at]?.disabled ? at : enabledFrom(0, 1));
    setOpen(true);
  }

  function pick(i: number) {
    const o = options[i];
    if (!o || o.disabled) return;
    if (controlled === undefined) setOwn(o.value);
    onChange?.({ target: { value: o.value, name } });
    setOpen(false);
    button.current?.focus();
  }

  function typeahead(key: string) {
    const now = Date.now();
    typed.current = { text: (now - typed.current.at > 600 ? "" : typed.current.text) + key.toLowerCase(), at: now };
    const from = open ? active : selectedIndex;
    const order = [...options.keys()].map((k) => (k + Math.max(0, from) + (typed.current.text.length === 1 ? 1 : 0)) % options.length);
    const hit = order.find((i) => !options[i].disabled && options[i].label.toLowerCase().startsWith(typed.current.text));
    if (hit === undefined) return;
    if (open) setActive(hit);
    else pick(hit);
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const k = event.key;
    if (!open) {
      if (k === "Enter" || k === " " || k === "ArrowDown" || k === "ArrowUp") {
        event.preventDefault();
        show();
      } else if (k.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) typeahead(k);
      return;
    }
    if (k === "ArrowDown") setActive((a) => (enabledFrom(a + 1, 1) >= 0 ? enabledFrom(a + 1, 1) : a));
    else if (k === "ArrowUp") setActive((a) => (enabledFrom(a - 1, -1) >= 0 ? enabledFrom(a - 1, -1) : a));
    else if (k === "Home") setActive(enabledFrom(0, 1));
    else if (k === "End") setActive(enabledFrom(options.length - 1, -1));
    else if (k === "Enter" || k === " ") pick(active);
    else if (k === "Escape") setOpen(false);
    else if (k === "Tab") {
      setOpen(false);
      return;
    } else if (k.length === 1) typeahead(k);
    else return;
    event.preventDefault();
  }

  const current = options[selectedIndex];
  const box = size === "md" ? "h-8.5 text-sm" : "h-7 text-xs";

  return (
    <span className={`relative inline-flex min-w-0 ${className.includes("w-") ? "" : "w-full"} ${className}`}>
      <button
        ref={button}
        id={id ?? autoId}
        type="button"
        role="combobox"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open ? optId(active) : undefined}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={onKeyDown}
        className={`${box} flex w-full cursor-pointer items-center gap-1.5 pr-2 pl-2.5 text-left ${FIELD_BASE} ${open ? "border-line-strong" : ""}`}
      >
        <span className={`min-w-0 flex-1 truncate ${current ? "text-ink" : "text-muted-text"}`}>{current?.label ?? placeholder}</span>
        <ChevronDown
          size={14}
          strokeWidth={1.8}
          aria-hidden
          className={`shrink-0 text-muted transition-transform duration-fast ease-out ${open ? "rotate-180" : ""}`}
        />
      </button>
      {name ? <input type="hidden" name={name} value={value} /> : null}

      {open ? (
        <Portal>
          <div
            ref={panel}
            style={HIDDEN}
            className={`${PANEL} max-w-[min(420px,calc(100vw-16px))] py-1`}
            onMouseDown={(e) => e.preventDefault()}
          >
            <ul id={listId} role="listbox" aria-label={ariaLabel} className="flex flex-col px-1">
              {options.map((o, i) => {
                const header = o.group && o.group !== options[i - 1]?.group;
                return (
                  <li key={`${o.group}:${o.value}`} role="presentation">
                    {header ? <p className="px-2.5 pt-2 pb-1 text-xs font-semibold text-muted-text">{o.group}</p> : null}
                    <div
                      id={optId(i)}
                      role="option"
                      data-value={o.value}
                      aria-selected={i === selectedIndex}
                      aria-disabled={o.disabled || undefined}
                      onMouseEnter={() => !o.disabled && setActive(i)}
                      onClick={() => pick(i)}
                      className={[
                        "flex h-8 min-w-0 items-center gap-2 rounded-sm px-2.5 text-sm",
                        o.disabled ? "cursor-not-allowed text-muted-text" : "cursor-pointer text-ink",
                        i === active && !o.disabled ? "bg-surface-2" : "",
                      ].join(" ")}
                    >
                      <span className="min-w-0 flex-1 truncate">{o.label}</span>
                      {i === selectedIndex ? <Check size={14} strokeWidth={2} className="shrink-0 text-action-text" aria-hidden /> : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        </Portal>
      ) : null}
    </span>
  );
}
