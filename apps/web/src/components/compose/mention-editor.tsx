"use client";

import { ArrowLeft, ChevronRight, Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { Badge, Spinner } from "@/components/ui";
import { catalogApi, errText, type CatalogPort } from "@/lib/api";
import { composable, matches, type LibraryItem } from "@/lib/library";

/**
 * Prompt with @ mentions (spec §2.3, Paper · 05 Composer · @ picker open).
 *
 * The prompt is a list of tokens: plain text and atomic mention chips. The
 * text being typed lives in one input at the end. Typing @ opens the
 * picker: level 1 lists parts (in this composition, then the library),
 * level 2 drills into a catalog part's real ports. Enter or Tab inserts,
 * → or "." drills in, ← goes back, Escape closes. Backspace on an empty
 * input deletes the whole previous chip. Clicking a chip reopens the picker
 * to replace it.
 */

export type Token = { type: "text"; text: string } | { type: "chip"; label: string; item: LibraryItem; feature?: string };

type Option =
  | { id: string; kind: "part"; item: LibraryItem; drill: boolean }
  | { id: string; kind: "feature"; label: string; detail: string; count?: number };

type Level = { item: LibraryItem; ports: CatalogPort[] | null; error: string | null };

const GROUPS: { kind: CatalogPort["kind"]; title: string; plural: string }[] = [
  { kind: "face", title: "Faces", plural: "faces" },
  { kind: "axis", title: "Axes", plural: "axes" },
  { kind: "point", title: "Points", plural: "points" },
];

export function chipLabel(item: LibraryItem, feature?: string) {
  return `@${item.name}${feature ? `.${feature}` : ""}`;
}

export function MentionEditor({
  library,
  tokens,
  onTokens,
  draft,
  onDraft: setDraft,
  onSubmit,
  disabled = false,
}: {
  library: LibraryItem[] | null;
  tokens: Token[];
  onTokens: (tokens: Token[]) => void;
  /** The text being typed after the last chip. Controlled so the page can send it. */
  draft: string;
  onDraft: (draft: string) => void;
  /** Enter with the picker closed. */
  onSubmit?: () => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [level, setLevel] = useState<Level | null>(null);
  const [active, setActive] = useState(0);
  const [replaceAt, setReplaceAt] = useState<number | null>(null);
  /* Ctrl/Cmd+A selects the whole prompt, chips included, so Backspace or Delete clears it all. */
  const [allSelected, setAllSelected] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();

  /* What follows the last @ in the draft is the picker query. */
  const at = draft.lastIndexOf("@");
  const query = open && at >= 0 ? draft.slice(at + 1) : "";

  const inComposition = useMemo(() => {
    const seen = new Map<string, LibraryItem>();
    tokens.forEach((t) => t.type === "chip" && seen.set(t.item.id, t.item));
    return [...seen.values()].filter((i) => matches(i, query));
  }, [tokens, query]);

  const fromLibrary = useMemo(
    () => (library ?? []).filter((i) => composable(i) && !inComposition.some((c) => c.id === i.id) && matches(i, query)).slice(0, 8),
    [library, inComposition, query],
  );

  const options: Option[] = useMemo(() => {
    if (level) {
      if (!level.ports) return [];
      return GROUPS.flatMap((g) => {
        const ports = level.ports!.filter((p) => p.kind === g.kind);
        if (!ports.length) return [];
        return [
          { id: `all-${g.kind}`, kind: "feature" as const, label: `${g.plural}[*]`, detail: `All ${g.plural}`, count: ports.length },
          ...ports.map((p) => ({ id: `port-${p.name}`, kind: "feature" as const, label: p.name, detail: p.label })),
        ];
      });
    }
    return [...inComposition, ...fromLibrary].map((item) => ({ id: item.id, kind: "part" as const, item, drill: item.source === "catalog" }));
  }, [level, inComposition, fromLibrary]);

  const activeIndex = Math.min(active, Math.max(0, options.length - 1));
  const optionId = (i: number) => `${listId}-opt-${i}`;

  function close() {
    setOpen(false);
    setLevel(null);
    setActive(0);
    setReplaceAt(null);
  }

  function commit(item: LibraryItem, feature?: string) {
    const chip: Token = { type: "chip", label: chipLabel(item, feature), item, feature };
    if (replaceAt !== null) {
      onTokens(tokens.map((t, i) => (i === replaceAt ? chip : t)));
    } else {
      const before = at >= 0 ? draft.slice(0, at) : draft;
      const next = [...tokens];
      if (before.trim()) next.push({ type: "text", text: before.trim() });
      next.push(chip);
      onTokens(next);
      setDraft("");
    }
    close();
    input.current?.focus();
  }

  function drill(item: LibraryItem) {
    setLevel({ item, ports: null, error: null });
    setActive(0);
    catalogApi
      .preview(item.name, {})
      .then((p) => setLevel((l) => (l?.item.id === item.id ? { ...l, ports: p.ports } : l)))
      .catch((e) => setLevel((l) => (l?.item.id === item.id ? { ...l, ports: [], error: errText(e) } : l)));
  }

  function choose(option: Option | undefined) {
    if (!option) return;
    if (option.kind === "part") commit(option.item);
    else if (level) commit(level.item, option.label);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      setAllSelected(tokens.length > 0);
      return;
    }
    if (allSelected) {
      setAllSelected(false);
      if (event.key === "Backspace" || event.key === "Delete") {
        event.preventDefault();
        onTokens([]);
        setDraft("");
        return;
      }
    }
    if (open) {
      const opt = options[activeIndex];
      if (event.key === "ArrowDown") setActive((activeIndex + 1) % Math.max(1, options.length));
      else if (event.key === "ArrowUp") setActive((activeIndex - 1 + options.length) % Math.max(1, options.length));
      else if (event.key === "Enter" || event.key === "Tab") choose(opt);
      else if ((event.key === "ArrowRight" || event.key === ".") && opt?.kind === "part" && opt.drill) drill(opt.item);
      else if ((event.key === "ArrowLeft" && level) || (event.key === "Backspace" && level && !query)) {
        setLevel(null);
        setActive(0);
      } else if (event.key === "Escape") close();
      else return;
      event.preventDefault();
      return;
    }
    if (event.key === "Enter" && onSubmit && !event.nativeEvent.isComposing) {
      event.preventDefault();
      onSubmit();
      return;
    }
    if (event.key === "Backspace" && draft === "" && tokens.length) {
      event.preventDefault();
      const last = tokens[tokens.length - 1];
      onTokens(tokens.slice(0, -1));
      /* Text is reopened for editing; a chip goes whole. */
      if (last.type === "text") setDraft(`${last.text} `);
    }
  }

  function reopen(index: number) {
    const token = tokens[index];
    if (token.type !== "chip" || disabled) return;
    setReplaceAt(index);
    setDraft(`@${token.item.name}`);
    setOpen(true);
    setActive(0);
    input.current?.focus();
  }

  useEffect(() => {
    if (!open) return;
    document.getElementById(optionId(activeIndex))?.scrollIntoView({ block: "nearest" });
  });

  return (
    <div className="relative">
      <div
        className="flex min-h-11 flex-wrap items-center gap-x-1.5 gap-y-1 text-lg text-ink"
        onClick={(e) => e.target === e.currentTarget && input.current?.focus()}
      >
        {tokens.map((t, i) =>
          t.type === "text" ? (
            <span key={i}>{t.text}</span>
          ) : (
            <button
              key={i}
              type="button"
              onClick={() => reopen(i)}
              aria-label={`${t.label}, change reference`}
              className={`inline-flex items-center rounded-sm px-2 py-0.5 text-lg font-semibold whitespace-nowrap ${allSelected ? "ring-2 ring-action" : ""} ${t.item.kind === "complex" ? "bg-complex-soft text-complex-text" : "bg-basic-soft text-basic-text"}`}
            >
              {t.label}
            </button>
          ),
        )}
        <input
          ref={input}
          value={draft}
          disabled={disabled}
          onChange={(e) => {
            const v = e.target.value;
            setDraft(v);
            if (v.endsWith("@") || (open && v.lastIndexOf("@") >= 0)) {
              if (!open) setActive(0);
              setOpen(true);
            } else if (open) close();
          }}
          onKeyDown={onKeyDown}
          onBlur={(e) => {
            setAllSelected(false);
            if (!e.relatedTarget?.closest?.("[data-picker]")) close();
          }}
          placeholder={tokens.length ? "" : "Type @ to pick a part, then say what to do with it"}
          aria-label="Composition prompt"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={open && options.length ? optionId(activeIndex) : undefined}
          className="h-8 min-w-[12ch] flex-1 bg-transparent text-lg text-ink placeholder:text-muted-text focus-visible:shadow-none disabled:cursor-not-allowed"
        />
      </div>

      {open ? (
        <Picker
          listId={listId}
          query={query}
          level={level}
          options={options}
          activeIndex={activeIndex}
          optionId={optionId}
          compositionCount={inComposition.length}
          loading={!library}
          onHover={setActive}
          onChoose={choose}
          onDrill={drill}
          onBack={() => {
            setLevel(null);
            setActive(0);
            input.current?.focus();
          }}
          onClose={close}
        />
      ) : null}
    </div>
  );
}

function Picker({
  listId,
  query,
  level,
  options,
  activeIndex,
  optionId,
  compositionCount,
  loading,
  onHover,
  onChoose,
  onDrill,
  onBack,
  onClose,
}: {
  listId: string;
  query: string;
  level: Level | null;
  options: Option[];
  activeIndex: number;
  optionId: (i: number) => string;
  compositionCount: number;
  loading: boolean;
  onHover: (i: number) => void;
  onChoose: (o: Option) => void;
  onDrill: (item: LibraryItem) => void;
  onBack: () => void;
  onClose: () => void;
}) {
  const row = (selected: boolean) =>
    `flex w-full min-w-0 cursor-pointer items-center gap-2.5 px-3 text-left transition-colors duration-fast ${selected ? "bg-action-soft" : "hover:bg-surface"}`;

  return (
    <>
      {/* Phone: the picker is a bottom sheet with a scrim. */}
      <button type="button" aria-label="Close picker" tabIndex={-1} onClick={onClose} className="fixed inset-0 z-40 bg-stage/30 sm:hidden" />
      <div
        data-picker
        onMouseDown={(e) => e.preventDefault()}
        className="fixed inset-x-0 bottom-0 z-50 flex max-h-[70dvh] flex-col overflow-hidden rounded-t-xl border border-line-strong bg-bg shadow-popover motion-safe:animate-[toast-in_var(--duration-base)_var(--ease-out)] sm:absolute sm:inset-x-auto sm:bottom-[calc(100%+20px)] sm:-left-3.5 sm:max-h-[min(328px,55dvh)] sm:w-[min(600px,calc(100vw-32px))] sm:rounded-lg"
      >
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-line px-3">
          {level ? (
            <>
              <button type="button" onClick={onBack} aria-label="Back to parts" className="-ml-1 rounded-sm p-1 text-muted-text hover:text-ink">
                <ArrowLeft size={14} strokeWidth={2} aria-hidden />
              </button>
              <span className="truncate text-sm font-semibold text-ink">@{level.item.name}.</span>
              <span className="hidden truncate text-xs text-muted-text sm:inline">ports from the catalog generator</span>
            </>
          ) : (
            <>
              <Search size={14} strokeWidth={2} className="shrink-0 text-muted" aria-hidden />
              <span className="text-sm text-ink">{query}</span>
              <span className="truncate text-sm text-muted-text">{query ? "" : "search name, standard, tag"}</span>
            </>
          )}
        </div>

        <ul id={listId} role="listbox" aria-label={level ? `Features of ${level.item.name}` : "Parts"} className="min-h-0 flex-1 overflow-y-auto pb-2">
          {level ? (
            level.ports === null ? (
              <li className="flex items-center gap-2 px-3 py-4 text-sm text-body">
                <Spinner /> Reading ports…
              </li>
            ) : level.error ? (
              <li className="px-3 py-4 text-sm text-fail-text">{level.error}</li>
            ) : options.length === 0 ? (
              <li className="px-3 py-4 text-sm text-body">This part has no named ports.</li>
            ) : (
              options.map((o, i) =>
                o.kind === "feature" ? (
                  <li
                    key={o.id}
                    id={optionId(i)}
                    role="option"
                    aria-selected={i === activeIndex}
                    onMouseEnter={() => onHover(i)}
                    onClick={() => onChoose(o)}
                    className={`${row(i === activeIndex)} ${o.count !== undefined ? "mt-1 h-10 border-t border-line bg-surface font-semibold first:mt-0 first:border-t-0" : "h-[30px] pl-5"}`}
                  >
                    <span className="min-w-0 flex-1 truncate text-sm text-ink">
                      {o.count !== undefined ? `${o.detail} · ` : ""}
                      <span className={o.count !== undefined ? "" : "font-semibold"}>{o.label}</span>
                      {o.count === undefined ? <span className="font-normal text-body"> · {o.detail}</span> : null}
                    </span>
                    {o.count !== undefined ? <span className="text-xs text-body tabular">{o.count}</span> : null}
                  </li>
                ) : null,
              )
            )
          ) : loading ? (
            <li className="flex items-center gap-2 px-3 py-4 text-sm text-body">
              <Spinner /> Loading the library…
            </li>
          ) : options.length === 0 ? (
            <li className="px-3 py-4 text-sm text-body">No parts match “{query}”.</li>
          ) : (
            options.map((o, i) =>
              o.kind === "part" ? (
                <li key={o.id} role="presentation">
                  {i === 0 && compositionCount > 0 ? <GroupLabel>In this composition</GroupLabel> : null}
                  {i === compositionCount ? <GroupLabel>Library</GroupLabel> : null}
                  <div
                    id={optionId(i)}
                    role="option"
                    aria-selected={i === activeIndex}
                    onMouseEnter={() => onHover(i)}
                    onClick={() => onChoose(o)}
                    className={`${row(i === activeIndex)} h-12`}
                  >
                    <span className="flex h-7 w-9 shrink-0 items-center justify-center rounded-sm bg-surface">
                      {/* eslint-disable-next-line @next/next/no-img-element -- decorative placeholder */}
                      <img src={o.item.thumb} alt="" className="size-6 object-contain" />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col gap-px">
                      <span className="truncate text-sm font-semibold text-ink">{o.item.name}</span>
                      <span className="truncate text-xs text-body">
                        {o.item.kind === "basic" ? "Basic" : "Complex"} · {o.item.source} · {o.item.summary}
                      </span>
                    </span>
                    {o.drill ? (
                      <button
                        type="button"
                        tabIndex={-1}
                        aria-label={`Features of ${o.item.name}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          onDrill(o.item);
                        }}
                        className="rounded-sm p-1 text-action-text hover:bg-bg"
                      >
                        <ChevronRight size={14} strokeWidth={2} aria-hidden />
                      </button>
                    ) : (
                      <Badge tone="consent" className="text-caption!">
                        Features planned
                      </Badge>
                    )}
                  </div>
                </li>
              ) : null,
            )
          )}
        </ul>
        <p className="hidden shrink-0 border-t border-line px-3 py-1.5 text-caption text-muted-text sm:block">
          ↑↓ move · Enter insert · → features · Esc close
        </p>
      </div>
    </>
  );
}

function GroupLabel({ children }: { children: string }) {
  return <p className="px-3 pt-2.5 pb-1 text-xs font-semibold text-muted-text">{children}</p>;
}
