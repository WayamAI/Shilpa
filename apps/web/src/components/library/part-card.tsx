import { ChevronRight } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui";
import type { LibraryItem } from "@/lib/library";

const SOURCE_LABEL = { catalog: "Catalog", native: "Native" } as const;

function Badges({ item }: { item: LibraryItem }) {
  return (
    <>
      <Badge tone={item.kind}>{item.kind === "basic" ? "Basic" : "Complex"}</Badge>
      <Badge tone="on-image">{SOURCE_LABEL[item.source]}</Badge>
    </>
  );
}

function Thumb({ item, className }: { item: LibraryItem; className: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- static webp thumbnail; decorative
    <img src={item.thumb} alt="" loading="lazy" decoding="async" draggable={false} className={`object-contain ${className}`} />
  );
}

/**
 * Part card (Paper · Foundations "Part cards" and 02 Library): 12px radius,
 * 1px line, 150px thumbnail well on surface, kind + source chips, name,
 * one-line summary, then a meta row. Whole card is one link.
 */
export function PartCard({ item }: { item: LibraryItem }) {
  return (
    <Link
      href={item.href}
      className="group flex min-w-0 flex-col overflow-hidden rounded-lg border border-line bg-bg transition-colors duration-fast ease-out hover:border-line-strong"
    >
      <div className="relative flex h-[150px] shrink-0 items-center justify-center bg-surface">
        <Thumb
          item={item}
          className={`transition-transform duration-base ease-out motion-safe:group-hover:scale-[1.03] ${item.thumbKind === "render" ? "h-[124px] w-[80%]" : "size-[72px]"}`}
        />
        <div className="absolute top-2.5 left-2.5 flex gap-1.5">
          <Badges item={item} />
        </div>
      </div>
      <div className="flex min-w-0 flex-col gap-1.5 px-3.5 pt-3 pb-3.5">
        <p className="truncate text-md font-semibold text-ink">{item.name}</p>
        <p className="truncate text-xs text-body">{item.summary}</p>
        <p className="flex min-w-0 gap-3 border-t border-line pt-1.5 text-xs text-body">
          {item.standard ? <span className="truncate">{item.standard}</span> : null}
          {item.family && item.source === "catalog" ? <span className="truncate">{item.family}</span> : null}
          {item.version !== null ? (
            <span>
              Version <span className="font-semibold text-ink tabular">v{item.version}</span>
            </span>
          ) : null}
        </p>
      </div>
    </Link>
  );
}

/** Phone row (Paper · 03 Mobile · Library): 56px thumb, name, chips + summary, chevron. */
export function PartRow({ item }: { item: LibraryItem }) {
  return (
    <Link href={item.href} className="flex min-h-[76px] items-center gap-3 border-b border-line px-4 py-2.5 transition-colors duration-fast hover:bg-surface">
      <span className="flex size-14 shrink-0 items-center justify-center rounded-lg bg-surface">
        <Thumb item={item} className={item.thumbKind === "render" ? "size-11" : "size-8"} />
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="truncate text-lg font-semibold text-ink">{item.name}</span>
        <span className="flex min-w-0 items-center gap-1.5">
          <Badge tone={item.kind}>{item.kind === "basic" ? "Basic" : "Complex"}</Badge>
          <span className="truncate text-xs text-body">
            {SOURCE_LABEL[item.source]} · {item.summary}
          </span>
        </span>
      </span>
      <ChevronRight size={16} strokeWidth={1.8} className="shrink-0 text-muted" aria-hidden />
    </Link>
  );
}
