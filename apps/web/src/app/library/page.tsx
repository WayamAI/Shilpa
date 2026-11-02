"use client";

import { Download, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { PartCard, PartRow } from "@/components/library/part-card";
import { Badge, Button, buttonClass, EmptyState, Segmented, Select, Skeleton, Tooltip } from "@/components/ui";
import { errText } from "@/lib/api";
import { loadLibrary, matches, type LibraryItem, type PartKind } from "@/lib/library";

type KindFilter = "all" | PartKind;

/**
 * Library (Paper · 02 Library, 03 Mobile M1). Everything @-mentionable in
 * one place: your models and the standard-parts catalog. Import is planned.
 */
export default function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<KindFilter>("all");
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("all");
  const [standard, setStandard] = useState("any");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    loadLibrary()
      .then((list) => !cancelled && (setItems(list), setError(null)))
      .catch((e) => !cancelled && setError(errText(e)));
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const standards = useMemo(
    () => [...new Set((items ?? []).map((i) => i.standard).filter((s): s is string => !!s))].sort((a, b) => a.localeCompare(b)),
    [items],
  );
  const counts = useMemo(() => {
    const all = items ?? [];
    return { all: all.length, basic: all.filter((i) => i.kind === "basic").length, complex: all.filter((i) => i.kind === "complex").length };
  }, [items]);
  const shown = useMemo(
    () =>
      (items ?? []).filter(
        (i) =>
          (kind === "all" || i.kind === kind) &&
          (source === "all" || i.source === source) &&
          (standard === "any" || i.standard === standard) &&
          matches(i, query),
      ),
    [items, kind, source, standard, query],
  );
  const filtered = kind !== "all" || source !== "all" || standard !== "any" || query.trim() !== "";

  function clear() {
    setKind("all");
    setSource("all");
    setStandard("any");
    setQuery("");
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Header: 24px title, summary line, actions. */}
      <div className="flex shrink-0 flex-col gap-3 px-4 pt-3 lg:flex-row lg:items-center lg:px-8 lg:pt-5 lg:pb-4">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h1 className="sr-only lg:not-sr-only lg:text-page">Library</h1>
          <p className="text-sm text-body">
            {items ? `${counts.all} parts · ` : ""}basic parts combine into complex parts · every part is @-mentionable
          </p>
        </div>
        <span className="hidden flex-1 lg:block" />
        <div className="flex flex-wrap gap-2">
          <Tooltip content="STEP and STL import is planned">
            <Button disabled icon={<Download size={14} strokeWidth={2} aria-hidden />} className="font-semibold">
              Import STEP / STL
              <Badge tone="consent">Planned</Badge>
            </Button>
          </Tooltip>
          <Link href="/compose" className={buttonClass("primary", "md")}>
            <Plus size={14} strokeWidth={2.2} aria-hidden />
            New complex part
          </Link>
        </div>
      </div>

      {/* Toolbar: kind, search, source, standard. */}
      <div className="flex shrink-0 flex-col gap-2.5 border-b border-line px-4 pt-3 pb-4 lg:flex-row lg:flex-wrap lg:items-center lg:px-8 lg:pt-0">
        <Segmented
          variant="filter"
          label="Part kind"
          value={kind}
          onChange={setKind}
          className="w-full lg:w-auto lg:shrink-0"
          options={[
            { id: "all", label: "All", count: items ? counts.all : undefined },
            { id: "basic", label: "Basic", count: items ? counts.basic : undefined },
            { id: "complex", label: "Complex", count: items ? counts.complex : undefined },
          ]}
        />
        <label className="flex h-8 w-full items-center gap-2 rounded-md border border-line px-2.5 transition-colors duration-fast focus-within:border-action hover:border-line-strong lg:w-[300px]">
          <Search size={14} strokeWidth={2} className="shrink-0 text-muted" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Name, standard, tag, designation"
            aria-label="Search parts"
            className="h-full min-w-0 flex-1 bg-transparent text-sm text-ink placeholder:text-muted-text focus-visible:shadow-none"
          />
        </label>
        <div className="flex gap-2.5">
          <Select size="sm" aria-label="Source" value={source} onChange={(e) => setSource(e.target.value)} className="flex-1 lg:w-36 lg:flex-none">
            <option value="all">Source: All</option>
            <option value="native">Native</option>
            <option value="catalog">Catalog</option>
            <option value="imported" disabled>
              Imported (planned)
            </option>
          </Select>
          <Select size="sm" aria-label="Standard" value={standard} onChange={(e) => setStandard(e.target.value)} className="flex-1 lg:w-44 lg:flex-none">
            <option value="any">Standard: Any</option>
            {standards.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </div>
        <span className="hidden flex-1 lg:block" />
        <p className="hidden text-sm text-body lg:block">Thumbnails are placeholder renders</p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto" aria-live="polite" aria-busy={!items && !error}>
        {error ? (
          <EmptyState
            image="/imagery/sh-emp-02-import-failed-128.webp"
            imageSize={48}
            title="The library didn't load"
            detail={error}
            actions={<Button onClick={() => setAttempt((a) => a + 1)}>Try again</Button>}
          />
        ) : !items ? (
          <LoadingGrid />
        ) : items.length === 0 ? (
          <EmptyState
            image="/imagery/sh-emp-01-empty-tray-128.webp"
            title="Your library is empty"
            detail="Import the STEP files you already have, or start from about 100 catalog parts: fasteners, bearings, gears, rails."
            actions={
              <Link href="/catalog" className={buttonClass("secondary")}>
                Browse catalog
              </Link>
            }
          />
        ) : shown.length === 0 ? (
          <EmptyState
            image="/imagery/sh-emp-01-empty-tray-128.webp"
            imageSize={48}
            title="No parts match"
            detail={filtered ? "Try a shorter search, or clear the filters." : undefined}
            actions={<Button onClick={clear}>Clear filters</Button>}
          />
        ) : (
          <>
            <ul className="hidden grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-4 px-8 py-5 sm:grid" aria-label="Parts">
              {shown.map((item) => (
                <li key={item.id} className="min-w-0">
                  <PartCard item={item} />
                </li>
              ))}
            </ul>
            <ul className="sm:hidden" aria-label="Parts">
              {shown.map((item) => (
                <li key={item.id}>
                  <PartRow item={item} />
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}

/** Paper · 10 States loading skeleton, as a card grid. */
function LoadingGrid() {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-4 px-4 py-5 lg:px-8" aria-label="Loading parts">
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} className="flex h-[236px] flex-col overflow-hidden rounded-lg border border-line">
          <div className="flex-1 bg-surface" />
          <div className="flex flex-col gap-1.5 p-3.5">
            <Skeleton className={`h-3 ${["w-[70%]", "w-[60%]", "w-[75%]"][i % 3]}`} />
            <Skeleton className={`h-2.5 ${["w-[45%]", "w-[40%]", "w-[35%]"][i % 3]}`} />
          </div>
        </div>
      ))}
    </div>
  );
}
