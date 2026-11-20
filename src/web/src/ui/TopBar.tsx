// The bar at the top of a page (UX-039, ADR-0111).
import type { ReactNode } from "react";

import { cx } from "./cx";

/**
 * The top bar: at its start the button that opens the conversation list, or Back, then where the user is,
 * with an optional line under it, and the page's own actions at its end. On a phone it is the only bar at the
 * top of the screen; `line` draws its lower edge.
 */
export function TopBar({
  start,
  title,
  detail,
  line = false,
  className,
  children,
}: {
  /** The button for the conversation list, or Back. */
  start?: ReactNode;
  /** Where the user is: the page's name, or a conversation's title. */
  title?: ReactNode;
  /** A line under the title, such as a conversation's cost on a phone. */
  detail?: ReactNode;
  line?: boolean;
  /** Where the bar shows: `md:hidden` for a bar of phones only. */
  className?: string;
  /** The page's actions, at the end of the bar. */
  children?: ReactNode;
}) {
  return (
    <div className={cx("flex h-14 flex-none items-center gap-2 px-3 md:px-4", line && "border-b border-line", className)}>
      {start}
      <div className="min-w-0 flex-1">
        {title !== undefined && <p className="truncate text-body font-semibold">{title}</p>}
        {detail}
      </div>
      {children}
    </div>
  );
}
