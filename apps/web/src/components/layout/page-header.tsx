import type { ReactNode } from "react";

/**
 * In-page header. The top bar says where you are; this says what this screen
 * is for and carries its scope controls.
 */
export function PageHeader({
  title,
  description,
  info,
  mark,
  actions,
  children,
}: {
  title: string;
  description?: string;
  /** Compact “i” popover beside the title how-to copy, not page chrome. */
  info?: ReactNode;
  /** Optional 3D mark beside the title. Does not replace the heading. */
  mark?: ReactNode;
  /** Filters, chips or buttons aligned to the right. */
  actions?: ReactNode;
  /** Optional second row, typically filter chips. */
  children?: ReactNode;
}) {
  return (
    <div className="shrink-0 px-4 pt-3 pb-3 lg:px-8 lg:pt-5 lg:pb-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2.5">
            {mark}
            {/* The phone header already shows the title; keep the h1 for assistive tech. */}
            <h1 className="sr-only min-w-0 lg:not-sr-only lg:text-page">{title}</h1>
            {info}
          </div>
          {description ? (
            <p className="max-w-[70ch] text-sm text-body lg:mt-0.5">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children ? <div className="mt-3 min-w-0">{children}</div> : null}
    </div>
  );
}

/** Standard scroll container for page bodies. */
export function PageBody({ children }: { children: ReactNode }) {
  return <div className="min-h-0 flex-1 overflow-y-auto px-4 pt-1 pb-6 lg:px-8 lg:pt-2">{children}</div>;
}
