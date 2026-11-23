// An entry of a list the user moves through: conversations, the settings' sections, a tree of files
// (UX-037, ADR-0111).
import type { ComponentProps, ReactNode } from "react";

/** The classes of an entry, for an entry that is a link. The current one is marked with `aria-current`. */
export const NAV_ITEM =
  "flex h-8 w-full min-w-0 cursor-pointer items-center gap-2 rounded-sm px-2 text-start text-body text-ink-2 transition-colors duration-120 hover:bg-hover hover:text-ink aria-[current]:bg-pressed aria-[current]:font-semibold aria-[current]:text-ink pointer-coarse:min-h-11 [&_svg]:size-4 [&_svg]:flex-none";

export function NavItem({
  current = false,
  icon,
  end,
  children,
  ...rest
}: Omit<ComponentProps<"button">, "className" | "aria-current"> & { current?: boolean | "page"; icon?: ReactNode; end?: ReactNode }) {
  return (
    <button type="button" aria-current={current || undefined} className={NAV_ITEM} {...rest}>
      {icon}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {end && <span className="flex-none text-caption text-ink-2">{end}</span>}
    </button>
  );
}

/** The label of a group of entries. */
export function NavLabel({ children, ...rest }: Omit<ComponentProps<"h2">, "className">) {
  return (
    <h2 className="px-2 pt-3 pb-1 text-caption font-medium text-ink-3" {...rest}>
      {children}
    </h2>
  );
}
