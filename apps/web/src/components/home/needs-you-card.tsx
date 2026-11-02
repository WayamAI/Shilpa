/* eslint-disable @next/next/no-img-element -- static decorative webp, already sized */
import Link from "next/link";

import { Badge, buttonClass, type BadgeTone } from "@/components/ui";
import type { NeedsYouItem } from "@/lib/api";

import { ago } from "./use-home";

const KIND: Record<NeedsYouItem["kind"], { image: string; badge: string; tone: BadgeTone }> = {
  clarification: { image: "sh-card-10-clarification", badge: "Question", tone: "consent" },
  drawing_review: { image: "sh-card-10-clarification", badge: "Review", tone: "consent" },
  failed_build: { image: "sh-card-25-solver-error", badge: "Build failed", tone: "fail" },
};

/** Where the card's action goes: the project, with the specification to answer when there is one. */
export function itemHref(item: NeedsYouItem): string {
  const base = `/projects/${item.link.project_id}`;
  return item.link.open === "specification" && item.link.specification_id ? `${base}?spec=${item.link.specification_id}` : base;
}

/** One inbox card (Paper · 01 Home, Needs you). Viewers see the item with a read-only "Open project". */
export function NeedsYouCard({ item }: { item: NeedsYouItem }) {
  const k = KIND[item.kind];
  const answer = item.link.open === "specification";
  const action = answer ? (item.can_act ? (item.kind === "drawing_review" ? "Review" : "Answer") : "Open project") : "Open project";
  return (
    <li className="flex min-w-0 flex-col gap-3 rounded-lg border border-line p-4">
      <div className="flex items-center gap-2">
        <img src={`/imagery/${k.image}-128.webp`} alt="" width={26} height={26} className="size-[26px] shrink-0" />
        <Badge tone={k.tone}>{k.badge}</Badge>
        <span className="ml-auto min-w-0 truncate text-xs text-muted-text">
          {item.project_name} · {ago(item.created_at)}
        </span>
      </div>
      <p className="text-md text-ink">
        <span className="font-semibold">{item.title}.</span> {item.detail}
        {item.model_name ? <span className="text-body"> Part: {item.model_name}.</span> : null}
      </p>
      <div className="mt-auto flex gap-2">
        <Link href={itemHref(item)} className={buttonClass("dark", "md")}>
          {action}
          <span className="sr-only">: {item.title}, {item.project_name}</span>
        </Link>
      </div>
    </li>
  );
}
