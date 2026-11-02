import type { SVGProps } from "react";

/**
 * Nav glyphs drawn in Paper · 00 Shell template (24 grid, 1.8 stroke,
 * round joins). Lucide has near matches, but these are the exact paths.
 */
function Glyph({ d, ...props }: SVGProps<SVGSVGElement> & { d: string }) {
  return (
    <svg
      width={16}
      height={16}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...props}
    >
      <path d={d} />
    </svg>
  );
}

export const HomeIcon = (p: SVGProps<SVGSVGElement>) => <Glyph d="M3 10.5L12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" {...p} />;
export const LibraryIcon = (p: SVGProps<SVGSVGElement>) => <Glyph d="M12 3l8 4.5v9L12 21l-8-4.5v-9z M4 7.5l8 4.5 8-4.5 M12 12v9" {...p} />;
export const ComposeIcon = (p: SVGProps<SVGSVGElement>) => <Glyph d="M4 20l4-1 11-11-3-3L5 16z M14 7l3 3" {...p} />;
export const ImportIcon = (p: SVGProps<SVGSVGElement>) => <Glyph d="M12 4v11 M7 10l5 5 5-5 M4 20h16" {...p} />;
export const FolderIcon = (p: SVGProps<SVGSVGElement>) => <Glyph d="M3 7a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" {...p} />;
export const NeedsYouIcon = (p: SVGProps<SVGSVGElement>) => <Glyph d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z M10 21h4" {...p} />;
export const SettingsIcon = (p: SVGProps<SVGSVGElement>) => (
  <Glyph d="M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2" {...p} />
);
export const SearchIcon = (p: SVGProps<SVGSVGElement>) => <Glyph d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M20 20l-3.5-3.5" strokeWidth={2} {...p} />;
