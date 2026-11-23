// The parts of the sidebar that the navigation item alone cannot say: an entry that is a link, with a second
// line and a menu of its own, and the mark of where a dragged entry may be dropped (UX-037, ADR-0111).
import type { ComponentProps, ReactNode } from "react";
import { NavLink } from "react-router";

import { cx } from "./cx";
import { NAV_ITEM } from "./NavItem";

/** The outline of the place that takes what is being dragged over it (CNV-019). */
export const DROP_TARGET = "outline-2 -outline-offset-2 outline-accent";

/**
 * An entry of a list that opens a page: a navigation item that is a link, marked with `aria-current` while its
 * page is open. It may have a line of detail under its title, a state at its end, and a menu that shows when
 * the entry is pointed at.
 */
export function NavEntry({
  to,
  title,
  detail,
  detailLines = 1,
  end,
  menu,
  dimmed = false,
  ...rest
}: Omit<ComponentProps<"li">, "className" | "children" | "title"> & {
  to: string;
  title: string;
  /** A line under the title, such as the task that started a conversation. */
  detail?: string | undefined;
  /** How many lines the detail may take before it is cut short. */
  detailLines?: 1 | 2;
  /** A short state at the end of the entry: a badge. */
  end?: ReactNode;
  /** The menu of the entry, at its end, over the link. */
  menu?: ReactNode;
  /** The entry is being moved somewhere else. */
  dimmed?: boolean;
}) {
  return (
    <li className={cx("group relative", dimmed && "opacity-50")} {...rest}>
      {/* With a detail the entry is as tall as its two lines; otherwise it has the height of every entry. */}
      <NavLink to={to} className={cx(NAV_ITEM, detail !== undefined && "h-auto! py-1")}>
        <span className="min-w-0 flex-1">
          <span className="block truncate">{title}</span>
          {detail !== undefined && <span className={cx("block text-caption font-normal text-ink-2", detailLines === 2 ? "line-clamp-2" : "truncate")}>{detail}</span>}
        </span>
        {end}
        {/* Room for the menu, which lies over the end of the link. */}
        {menu !== undefined && <span aria-hidden="true" className="w-6 flex-none pointer-coarse:w-8" />}
      </NavLink>
      {menu !== undefined && <span className="absolute inset-y-0 end-0 flex items-center">{menu}</span>}
    </li>
  );
}
