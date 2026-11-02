import { forwardRef, type ComponentPropsWithoutRef, type ReactNode } from "react";

import { Spinner } from "./feedback";

/**
 * Buttons (Paper · Foundations · "Buttons and status pills").
 * 34px tall, 8px radius, 14px side padding, 13px label.
 * One primary per screen; destructive uses the AA fail shade.
 */

export type ButtonVariant = "primary" | "secondary" | "dark" | "ghost" | "danger";
export type ButtonSize = "lg" | "md" | "sm";

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-[image:var(--action-gradient)] text-on-action font-semibold shadow-action hover:bg-none hover:bg-action-hover active:bg-none active:bg-action-pressed",
  secondary:
    "border border-line-strong bg-bg text-ink hover:bg-surface active:bg-surface-2",
  dark: "bg-ink text-white font-semibold hover:bg-stage-2 active:bg-stage",
  ghost: "text-body hover:bg-surface-2 hover:text-ink active:bg-line",
  danger: "bg-fail-text text-white font-semibold hover:bg-fail-text/90 active:bg-fail-text/80",
};

const SIZE: Record<ButtonSize, string> = {
  lg: "h-[42px] gap-2 px-4 text-md",
  md: "h-8.5 gap-2 px-3.5 text-sm",
  sm: "h-7 gap-1.5 px-2.5 text-xs",
};

export const BUTTON_BASE =
  "inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap rounded-md transition-[background-color,color,border-color] duration-fast ease-out disabled:pointer-events-none disabled:opacity-45 aria-busy:pointer-events-none";

export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", className = "") {
  return [BUTTON_BASE, VARIANT[variant], SIZE[size], className].join(" ");
}

type ButtonProps = ComponentPropsWithoutRef<"button"> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner, keeps the label for width, and sets aria-busy. */
  loading?: boolean;
  icon?: ReactNode;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading = false, icon, className = "", children, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      {...props}
      disabled={disabled}
      aria-busy={loading || undefined}
      className={buttonClass(variant, size, className)}
    >
      {loading ? <Spinner size={size === "sm" ? 12 : 14} /> : icon}
      {children}
    </button>
  );
});

/** Square icon control. The label is required: it is the accessible name and the tooltip. */
export const IconButton = forwardRef<
  HTMLButtonElement,
  ComponentPropsWithoutRef<"button"> & { label: string; size?: ButtonSize; pressed?: boolean }
>(function IconButton({ label, size = "md", pressed, className = "", children, ...props }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      {...props}
      className={[
        BUTTON_BASE,
        size === "sm" ? "size-7" : "size-8.5",
        "text-body hover:bg-surface-2 hover:text-ink active:bg-line aria-pressed:bg-surface-2 aria-pressed:text-ink",
        className,
      ].join(" ")}
    >
      {children}
    </button>
  );
});
