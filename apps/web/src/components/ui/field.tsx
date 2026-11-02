"use client";

import { Check, ChevronDown } from "lucide-react";
import {
  cloneElement,
  forwardRef,
  isValidElement,
  useId,
  type ComponentPropsWithoutRef,
  type ReactElement,
  type ReactNode,
} from "react";

/**
 * Form controls. Paper's field is the rail search box: white, 1px line,
 * 8px radius, 13px text. Height matches buttons (34px). Errors set
 * aria-invalid, which draws the fail border, and link the message with
 * aria-describedby.
 */

export const FIELD_BASE =
  "min-w-0 rounded-md border border-line bg-bg text-sm text-ink placeholder:text-muted-text transition-[border-color,box-shadow] duration-fast ease-out hover:border-line-strong focus-visible:border-action disabled:bg-surface disabled:text-muted-text disabled:hover:border-line aria-invalid:border-fail aria-invalid:focus-visible:shadow-[0_0_0_2px_var(--color-bg),0_0_0_4px_var(--color-fail)]";

type FieldChild = ReactElement<{ id?: string; "aria-describedby"?: string; "aria-invalid"?: boolean }>;

/** Label above, then the control, then a hint or an error. Sentence case, no tracking. */
export function Field({
  label,
  hint,
  error,
  children,
  className = "",
}: {
  label: string;
  hint?: ReactNode;
  error?: ReactNode;
  children: FieldChild;
  className?: string;
}) {
  const id = useId();
  const noteId = `${id}-note`;
  const control = isValidElement(children)
    ? cloneElement(children, {
        id: children.props.id ?? id,
        "aria-describedby": hint || error ? noteId : undefined,
        "aria-invalid": error ? true : children.props["aria-invalid"],
      })
    : children;
  return (
    <div className={`flex min-w-0 flex-col gap-1.5 ${className}`}>
      <label htmlFor={children.props.id ?? id} className="text-xs font-semibold text-ink">
        {label}
      </label>
      {control}
      {error ? (
        <p id={noteId} className="text-xs text-fail-text">
          {error}
        </p>
      ) : hint ? (
        <p id={noteId} className="text-xs text-muted-text">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export const TextInput = forwardRef<HTMLInputElement, ComponentPropsWithoutRef<"input">>(function TextInput(
  { className = "", ...props },
  ref,
) {
  return <input ref={ref} {...props} className={`h-8.5 w-full px-2.5 ${FIELD_BASE} ${className}`} />;
});

/** Dense numeric cell: numbers right-aligned, tabular. */
export const NumberInput = forwardRef<HTMLInputElement, ComponentPropsWithoutRef<"input">>(function NumberInput(
  { className = "", ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      type="number"
      step="any"
      inputMode="decimal"
      {...props}
      className={`h-7 w-24 px-2 text-right tabular ${FIELD_BASE} ${className}`}
    />
  );
});

export const Textarea = forwardRef<HTMLTextAreaElement, ComponentPropsWithoutRef<"textarea">>(function Textarea(
  { className = "", ...props },
  ref,
) {
  return <textarea ref={ref} {...props} className={`min-h-[84px] w-full resize-none px-2.5 py-2 text-prose ${FIELD_BASE} ${className}`} />;
});

/** Native select: keeps platform keyboard and mobile pickers. */
export const Select = forwardRef<HTMLSelectElement, Omit<ComponentPropsWithoutRef<"select">, "size"> & { size?: "md" | "sm" }>(
  function Select({ className = "", size = "md", children, ...props }, ref) {
    return (
      <span className={`relative inline-flex min-w-0 ${className.includes("w-") ? "" : "w-full"} ${className}`}>
        <select
          ref={ref}
          {...props}
          className={`${size === "md" ? "h-8.5" : "h-7 text-xs"} w-full cursor-pointer appearance-none pr-8 pl-2.5 ${FIELD_BASE}`}
        >
          {children}
        </select>
        <ChevronDown
          size={14}
          strokeWidth={1.8}
          aria-hidden
          className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-muted"
        />
      </span>
    );
  },
);

/* ---------------------------------------------------------------------------
   Checkbox and radio. A real input under a drawn box, so keyboard, forms and
   screen readers behave natively. [Assumption] Paper has no checkbox: drawn
   from the field and action tokens.
   ------------------------------------------------------------------------ */

type ChoiceProps = Omit<ComponentPropsWithoutRef<"input">, "type"> & { label: ReactNode; detail?: ReactNode };

function Choice({ type, label, detail, className = "", ...props }: ChoiceProps & { type: "checkbox" | "radio" }) {
  const round = type === "radio";
  return (
    <label className={`group/choice flex min-w-0 cursor-pointer items-start gap-2.5 has-disabled:cursor-not-allowed has-disabled:opacity-45 ${className}`}>
      <span className="relative mt-px inline-flex size-4 shrink-0">
        <input
          type={type}
          {...props}
          className={`peer size-4 cursor-pointer appearance-none border border-line-strong bg-bg transition-colors duration-fast ease-out checked:border-action checked:bg-action hover:border-muted disabled:cursor-not-allowed aria-invalid:border-fail ${round ? "rounded-full" : "rounded-[4px]"}`}
        />
        {round ? (
          <span aria-hidden className="pointer-events-none absolute inset-0 m-auto size-1.5 rounded-full bg-white opacity-0 peer-checked:opacity-100" />
        ) : (
          <Check
            size={12}
            strokeWidth={3}
            aria-hidden
            className="pointer-events-none absolute inset-0 m-auto text-white opacity-0 peer-checked:opacity-100"
          />
        )}
      </span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="text-sm text-ink">{label}</span>
        {detail ? <span className="text-xs text-muted-text">{detail}</span> : null}
      </span>
    </label>
  );
}

export function Checkbox(props: ChoiceProps) {
  return <Choice type="checkbox" {...props} />;
}

export function Radio(props: ChoiceProps) {
  return <Choice type="radio" {...props} />;
}
