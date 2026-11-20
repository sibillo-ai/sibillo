// The parts of a side panel, such as the files of a conversation: its header, the entries of its tree, a
// meter, the frame of a code block or a preview, and the sheets it opens (UX-037, UX-019, ADR-0111).
import * as Primitive from "@radix-ui/react-dialog";
import { ChevronRight, X } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import { IconButton } from "./Button";
import { cx } from "./cx";

/**
 * The bar at the top of a panel: its title, then its icon buttons. In a sheet the title names the sheet;
 * beside the page it has the `id` the panel is labelled by.
 */
export function PanelHeader({ title, titleId, sheet = false, children }: { title: string; titleId?: string | undefined; sheet?: boolean; children?: ReactNode }) {
  const heading = "min-w-0 flex-1 truncate text-body font-semibold";
  return (
    <header className="flex h-14 flex-none items-center gap-1 border-b border-line px-4">
      {sheet ? (
        <Primitive.Title className={heading}>{title}</Primitive.Title>
      ) : (
        <h2 id={titleId} className={heading}>
          {title}
        </h2>
      )}
      {children}
    </header>
  );
}

/** A panel as a sheet that fills a phone's screen (UX-019). Its `PanelHeader` names it. */
export function PanelSheet({ open, onOpenChange, children }: { open: boolean; onOpenChange: (open: boolean) => void; children: ReactNode }) {
  return (
    <Primitive.Root open={open} onOpenChange={onOpenChange}>
      <Primitive.Portal>
        {/* Below the dialogs it opens, and below their scrim. */}
        <Primitive.Content
          aria-describedby={undefined}
          className="fixed inset-0 z-40 flex flex-col bg-canvas pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] text-ink outline-none"
        >
          {children}
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}

/** One thing shown as large as the window allows, over a scrim: a file out of its panel (ART-001). */
export function Viewer({
  open,
  onClose,
  title,
  description,
  closeLabel,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  /** What the viewer is, for assistive technologies. */
  description: string;
  closeLabel: string;
  children: ReactNode;
}) {
  return (
    <Primitive.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Primitive.Portal>
        <Primitive.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Primitive.Content className="fixed inset-2 z-50 flex flex-col overflow-hidden rounded-lg bg-raised text-ink shadow-above outline-none sm:inset-6">
          <header className="flex h-14 flex-none items-center gap-2 border-b border-line px-4">
            <Primitive.Title className="min-w-0 flex-1 truncate text-body font-semibold">{title}</Primitive.Title>
            <Primitive.Description className="sr-only">{description}</Primitive.Description>
            <Primitive.Close asChild>
              <IconButton label={closeLabel}>
                <X aria-hidden="true" />
              </IconButton>
            </Primitive.Close>
          </header>
          <div className="min-h-0 flex-1 overflow-auto p-4">{children}</div>
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}

/**
 * An entry of a tree, looking like a navigation item: indented by its level, with a chevron when it is a
 * folder. It is the `treeitem`, named by its content; the tree that holds it moves the focus between entries.
 */
export function TreeEntry({
  level,
  path,
  selected,
  expanded,
  focusable,
  icon,
  end,
  onClick,
  children,
}: {
  /** The depth of the entry, from 1. */
  level: number;
  path: string;
  selected: boolean;
  /** Whether a folder is open; left out for what is not a folder. */
  expanded?: boolean | undefined;
  /** The one entry of the tree that Tab reaches. */
  focusable: boolean;
  icon: ReactNode;
  end?: ReactNode;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <div
      role="treeitem"
      aria-level={level}
      aria-selected={selected}
      aria-expanded={expanded}
      data-path={path}
      tabIndex={focusable ? 0 : -1}
      onClick={onClick}
      style={{ "--depth": level - 1 } as CSSProperties}
      className="flex h-8 w-full min-w-0 cursor-pointer items-center gap-2 rounded-sm pr-2 pl-[calc(0.5rem+var(--depth)*1rem)] text-body text-ink-2 transition-colors duration-120 hover:bg-hover hover:text-ink focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent aria-selected:bg-pressed aria-selected:font-semibold aria-selected:text-ink pointer-coarse:min-h-11 [&_svg]:size-4 [&_svg]:flex-none"
    >
      <ChevronRight className={cx("text-ink-3 transition-transform duration-120", expanded === undefined && "invisible", expanded && "rotate-90")} aria-hidden="true" />
      {icon}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {end && <span className="flex flex-none gap-2 text-caption font-normal text-ink-2 tabular-nums">{end}</span>}
    </div>
  );
}

/** How much of something is used: a thin line that fills. */
export function Meter({ label, value, max, text }: { label: string; value: number; max: number; /** The value in words. */ text: string }) {
  const percent = Math.min(100, Math.round((value / Math.max(1, max)) * 100));
  return (
    <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-valuetext={text} className="h-1 overflow-hidden rounded-full bg-hover">
      {/* A sliver even when nearly empty, so that the meter reads as one. */}
      <div className={percent >= 90 ? "h-full rounded-full bg-danger" : "h-full rounded-full bg-ink-2"} style={{ width: `${Math.max(3, percent)}%` }} />
    </div>
  );
}

/**
 * The frame of a code block or of a file's preview: a small header that says what it holds, with its icon
 * buttons, and the content below. `flush` is the same inside another frame: the header and the content, no box.
 */
export function CodeFrame({ title, actions, flush = false, children }: { title: ReactNode; actions?: ReactNode; flush?: boolean; children?: ReactNode }) {
  return (
    <div className={cx("min-w-0", !flush && "overflow-hidden rounded-md border border-line bg-surface")}>
      {/* Not a `header`: outside the page's main content that would be a second banner. */}
      <div className={cx("flex min-h-8 items-center gap-1 pr-1 text-caption font-medium text-ink-3", flush ? "pl-0" : "pl-3", children !== undefined && "border-b border-line")}>
        <div className="min-w-0 flex-1">{title}</div>
        {actions}
      </div>
      {children}
    </div>
  );
}
