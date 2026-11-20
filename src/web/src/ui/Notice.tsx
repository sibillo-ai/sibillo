// Messages in place, and what a list shows when it has nothing (UX-014, UX-038, ADR-0111).
import type { ReactNode } from "react";

import { cx } from "./cx";

/** A message in place, with at most one action. */
export function Notice({
  tone = "neutral",
  icon,
  title,
  action,
  role,
  children,
}: {
  tone?: "neutral" | "warn" | "error";
  /** A note is read in place; a status or an alert is announced when it appears. */
  role?: "note" | "status" | "alert";
  icon?: ReactNode;
  title?: string;
  action?: ReactNode;
  children?: ReactNode;
}) {
  const tones = { neutral: "bg-hover text-ink-2", warn: "bg-warn-soft text-warn", error: "bg-danger-soft text-danger" };
  return (
    <div role={role ?? (tone === "error" ? "alert" : "status")} className={cx("flex items-start gap-3 rounded-md px-4 py-3 text-small [&>svg]:mt-px [&>svg]:size-4 [&>svg]:flex-none", tones[tone])}>
      {icon}
      <div className="min-w-0 flex-1 text-ink">
        {title && <strong className="font-semibold">{title} </strong>}
        {children}
      </div>
      {action}
    </div>
  );
}

/** What a list is for, and the action that adds its first entry. */
export function EmptyState({ icon, title, action, children }: { icon: ReactNode; title: string; action?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <span aria-hidden="true" className="mb-2 grid size-12 place-items-center rounded-full bg-hover text-ink-2 [&_svg]:size-5">
        {icon}
      </span>
      <p className="text-body font-semibold">{title}</p>
      {children && <p className="max-w-sm text-small text-ink-2">{children}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
