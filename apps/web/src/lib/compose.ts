import { catalogApi, type ComposeMentionIn } from "@/lib/api";
import type { Token } from "@/components/compose/mention-editor";

/** The mention text the compose parser accepts: a slug of the part name, then the picked feature. */
export function mentionText(name: string, feature?: string): string {
  const slug = name.replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || "part";
  return `@${slug}${feature ? `.${feature}` : ""}`;
}

export type BuiltPrompt = { prompt: string; mentions: ComposeMentionIn[] };

/**
 * Prose for the planner, with each chip written as its mention text, plus the
 * chips pinned as the API expects (docs/compose.md, interpret request):
 * native parts pin the model id (the API pins the head version); catalog parts
 * pin the generator with its default parameters, read from the catalog preview.
 * If a preview fails the chip is sent unpinned and the API looks it up by name.
 */
export async function buildPrompt(tokens: Token[], draft: string): Promise<BuiltPrompt> {
  const parts: string[] = [];
  const pins = new Map<string, Promise<ComposeMentionIn | null>>();
  for (const t of tokens) {
    if (t.type === "text") {
      parts.push(t.text);
      continue;
    }
    const text = mentionText(t.item.name, t.feature);
    parts.push(text);
    if (pins.has(text)) continue;
    if (t.item.source === "native") {
      pins.set(text, Promise.resolve({ text, ref: { item: t.item.id.replace(/^model:/, "") } }));
    } else {
      pins.set(
        text,
        catalogApi
          .preview(t.item.name, {})
          .then((p): ComposeMentionIn => ({ text, ref: { item: t.item.id, params: p.params } }))
          .catch(() => null),
      );
    }
  }
  if (draft.trim()) parts.push(draft.trim());
  const mentions = (await Promise.all(pins.values())).filter((m): m is ComposeMentionIn => m !== null);
  return { prompt: parts.join(" ").replace(/\s+/g, " ").trim(), mentions };
}

/** Plain text of the job events the compose page shows. */
export function eventText(type: string, data: Record<string, unknown>): string {
  switch (type) {
    case "state.queued":
      return "Queued";
    case "state.planning":
      return "Preparing the build";
    case "state.executing":
      return data.instances ? `Building the assembly, ${data.instances} instances` : "Building the assembly";
    case "attempt.started":
      return "Geometry worker running";
    case "state.succeeded":
      return `Published version ${data.number ?? ""}`.trim();
    case "state.failed":
      return `Failed: ${(data.error as { message?: string } | undefined)?.message ?? "unknown error"}`;
    case "state.cancelled":
      return "Cancelled";
    case "progress":
      return String(data.message ?? "Working");
    default:
      return type;
  }
}
