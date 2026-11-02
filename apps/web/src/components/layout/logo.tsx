import Link from "next/link";

/**
 * Shilpa brand: the orange solid tile plus a Michroma wordmark. Same
 * construction as the Chronos logo, different mark.
 */
export function Logo({
  wordmark = false,
  className = "",
  href = "/projects",
}: {
  wordmark?: boolean;
  className?: string;
  /** Pass `false` on the sign-in surface so the mark is not a dead link. */
  href?: string | false;
}) {
  const mark = (
    <>
      {/* eslint-disable-next-line @next/next/no-img-element -- tiny static SVG, no optimisation needed */}
      <img src="/brand/shilpa-mark.svg" alt="" width={32} height={32} className="size-8 shrink-0 rounded-[10px]" />
      {wordmark ? (
        <span className="text-lg font-semibold leading-none text-ink">Shilpa</span>
      ) : null}
    </>
  );
  const frame = `flex min-w-0 items-center gap-2.5 ${className}`;
  if (!href) return <span className={frame}>{mark}</span>;
  return (
    <Link href={href} aria-label="Shilpa home" className={`${frame} outline-none focus-visible:ring-2 focus-visible:ring-line-strong`}>
      {mark}
    </Link>
  );
}
