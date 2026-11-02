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
    <div className="shrink-0 border-b border-line px-4 py-4 sm:px-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2.5">
            {mark}
            <h2 className="min-w-0 text-lg font-semibold text-ink sm:text-xl">{title}</h2>
            {info}
          </div>
          {description ? (
            <p className="mt-1 max-w-[70ch] text-sm text-muted-text">{description}</p>
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
  return <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">{children}</div>;
}
