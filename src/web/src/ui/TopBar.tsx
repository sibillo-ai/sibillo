// The bar at the top of a page (UX-039, ADR-0111).
import type { ReactNode } from "react";

import { cx } from "./cx";

/**
 * The top bar: at its start the button that opens the conversation list, or Back, then where the user is,
 * with an optional line under it, and the page's own actions at its end. On a phone it is the only bar at the
 * top of the screen; `line` draws its lower edge, and `below` is a second line of the bar, for what one line has
 * no room for.
 */
export function TopBar({
  start,
  title,
  detail,
  below,
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
  /** A second line of the bar, such as a conversation's model and cost on a phone; its classes say where it shows. */
  below?: { className?: string; children: ReactNode };
  line?: boolean;
  /** Where the bar shows: `md:hidden` for a bar of phones only. */
  className?: string;
  /** The page's actions, at the end of the bar. */
  children?: ReactNode;
}) {
  return (
    <div className={cx("flex flex-none flex-col", line && "border-b border-line", className)}>
      <div className="flex h-14 items-center gap-2 px-3 md:px-4">
        {start}
        <div className="min-w-0 flex-1">
          {title !== undefined && <p className="truncate text-body font-semibold">{title}</p>}
          {detail}
        </div>
        {children}
      </div>
      {below && <div className={cx("-mt-2 flex h-11 min-w-0 items-center gap-2 px-3 md:px-4", below.className)}>{below.children}</div>}
    </div>
  );
}
