import Link from "next/link";

/** Shilpa mark: the orange cube from Paper (paper-logos/shilpa.png). */
export function Mark({ size = 24 }: { size?: 24 | 26 | 32 | 48 }) {
  const radius = size <= 26 ? "rounded-[6px]" : size === 32 ? "rounded-[8px]" : "rounded-[12px]";
  return (
    // eslint-disable-next-line @next/next/no-img-element -- 1–3 KB static webp, no optimisation needed
    <img
      src={size > 32 ? "/brand/shilpa-mark-128.webp" : "/brand/shilpa-mark-64.webp"}
      alt=""
      width={size}
      height={size}
      className={`shrink-0 select-none ${radius}`}
      draggable={false}
    />
  );
}

/** Mark plus the 15px semibold wordmark (Paper rail header). */
export function Logo({ href = "/home", className = "" }: { href?: string | false; className?: string }) {
  const body = (
    <>
      <Mark />
      <span className="text-brand font-semibold text-ink">Shilpa</span>
    </>
  );
  const frame = `flex min-w-0 items-center gap-[9px] rounded-sm ${className}`;
  return href ? (
    <Link href={href} className={frame} aria-label="Shilpa, go to home">
      {body}
    </Link>
  ) : (
    <span className={frame}>{body}</span>
  );
}
