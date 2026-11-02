/**
 * @ mention chip (Paper · Foundations "@ mention chip"): soft tint by part
 * kind, 14px semibold. Text uses the AA shade of the hue.
 */
export type MentionKind = "basic" | "complex" | "feature";

const KIND: Record<MentionKind, string> = {
  basic: "bg-basic-soft text-basic-text",
  complex: "bg-complex-soft text-complex-text",
  feature: "bg-action-soft text-action-text",
};

export function MentionChip({ children, kind = "basic", className = "" }: { children: string; kind?: MentionKind; className?: string }) {
  return (
    <span title={children} className={`inline-block max-w-full truncate rounded-sm px-2 py-0.5 align-bottom text-md font-semibold whitespace-nowrap ${KIND[kind]} ${className}`}>
      {children.startsWith("@") ? children : `@${children}`}
    </span>
  );
}
