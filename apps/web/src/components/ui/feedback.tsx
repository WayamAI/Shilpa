import type { ReactNode } from "react";

/* ---------------------------------------------------------------------------
   Badges (Paper status pills): soft tint, 12px semibold, 2/8 padding.
   Text uses the AA *-text shade of each hue.
   ------------------------------------------------------------------------ */

export type BadgeTone = "neutral" | "basic" | "complex" | "pass" | "fail" | "consent" | "ai" | "action" | "on-image";

const BADGE: Record<BadgeTone, string> = {
  neutral: "bg-surface-2 text-body",
  basic: "bg-basic-soft text-basic-text",
  complex: "bg-complex-soft text-complex-text",
  pass: "bg-pass-soft text-pass-text",
  fail: "bg-fail-soft text-fail-text",
  consent: "bg-consent-soft text-consent-text",
  ai: "bg-ai-soft text-ai-text",
  action: "bg-action-soft text-action-text",
  /* White pill over a thumbnail (Paper part card source chip). */
  "on-image": "bg-bg text-body",
};

export function Badge({ tone = "neutral", children, className = "" }: { tone?: BadgeTone; children: ReactNode; className?: string }) {
  return (
    <span
      className={`inline-flex max-w-full shrink-0 items-center truncate rounded-full px-2 py-0.5 text-xs font-semibold ${BADGE[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

const DOT: Record<BadgeTone, string> = {
  neutral: "bg-line-strong",
  basic: "bg-basic",
  complex: "bg-complex",
  pass: "bg-pass",
  fail: "bg-fail",
  consent: "bg-consent",
  ai: "bg-ai",
  action: "bg-action",
  "on-image": "bg-bg",
};

/** 6px status dot (Paper engine status). Decorative: pair it with text. */
export function Dot({ tone = "neutral" }: { tone?: BadgeTone }) {
  return <span className={`inline-block size-1.5 shrink-0 rounded-[3px] ${DOT[tone]}`} aria-hidden />;
}

/* ---------------------------------------------------------------------------
   Loading
   ------------------------------------------------------------------------ */

export function Spinner({ size = 14, label }: { size?: number; label?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className="shrink-0 animate-spin motion-reduce:animate-none"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

/** Placeholder block (Paper loading skeleton: surface-2, 4px radius). */
export function Skeleton({ className = "" }: { className?: string }) {
  return <span aria-hidden className={`block rounded-[4px] bg-surface-2 motion-safe:animate-pulse ${className}`} />;
}

/** 4px progress bar (Paper loading state). Omit value for indeterminate. */
export function Progress({ value, label }: { value?: number; label: string }) {
  const pct = value === undefined ? undefined : Math.max(0, Math.min(100, value));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      className="h-1 w-full overflow-hidden rounded-[2px] bg-surface-2"
    >
      <div
        className={`h-full rounded-[2px] bg-action transition-[width] duration-slow ease-out ${pct === undefined ? "w-1/3 motion-safe:animate-pulse" : ""}`}
        style={pct === undefined ? undefined : { width: `${pct}%` }}
      />
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Empty and error states (Paper · 10 States)
   ------------------------------------------------------------------------ */

export function EmptyState({
  image,
  imageSize = 64,
  eyebrow,
  title,
  detail,
  actions,
  align = "center",
  className = "",
}: {
  /** Path under /imagery. Decorative: the title carries the meaning. */
  image?: string;
  imageSize?: 48 | 64 | 96;
  eyebrow?: ReactNode;
  title: string;
  detail?: ReactNode;
  actions?: ReactNode;
  align?: "center" | "start";
  className?: string;
}) {
  const centered = align === "center";
  return (
    <div
      className={`flex h-full min-h-[200px] w-full flex-col gap-3 p-7 ${centered ? "items-center justify-center text-center" : "items-start justify-center"} ${className}`}
    >
      {image ? (
        // eslint-disable-next-line @next/next/no-img-element -- static decorative webp, already sized
        <img src={image} alt="" width={imageSize} height={imageSize} className="shrink-0 select-none" draggable={false} />
      ) : null}
      {eyebrow}
      <p className="text-heading font-semibold text-ink">{title}</p>
      {detail ? <div className="max-w-[46ch] text-prose text-body">{detail}</div> : null}
      {actions ? <div className="mt-1 flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
