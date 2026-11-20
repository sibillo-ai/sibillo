// Pages are a header and groups; a group is a card of rows (UX-037, ADR-0111).
import { createContext, type ReactNode, useContext, useId } from "react";

import { cx } from "./cx";

/** Pages under a top bar that names them on a phone, as the settings' sections are (UX-039): their title is then not shown twice. */
export const NamedByTopBar = createContext(false);

/** The title of a page, in the voice of the house, and what the page is for. */
export function PageHeader({ title, id, children }: { title: string; id?: string; children?: ReactNode }) {
  const named = useContext(NamedByTopBar);
  return (
    <header className="flex flex-col gap-2">
      <h1 id={id} className={cx("font-serif text-display", named && "max-md:sr-only")}>
        {title}
      </h1>
      {children && <p className="max-w-prose text-body text-ink-2">{children}</p>}
    </header>
  );
}

/** A page of the form width: a region named by its header, then its groups. */
export function Page({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  const heading = useId();
  return (
    <section aria-labelledby={heading} className="flex min-w-0 flex-col gap-8">
      <PageHeader title={title} id={heading}>
        {description}
      </PageHeader>
      {children}
    </section>
  );
}

/**
 * A heading, an optional description and an optional action, above what they are about: usually a card.
 * With a `role` it is a landmark or a group of controls, named by its heading.
 */
export function Group({
  title,
  description,
  action,
  role,
  children,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  role?: "region" | "group";
  children: ReactNode;
}) {
  const heading = useId();
  return (
    <section {...(role ? { role, "aria-labelledby": heading } : {})} className="flex min-w-0 flex-col gap-3">
      <header className="flex items-end gap-4">
        <div className="min-w-0 flex-1">
          <h2 id={heading} className="text-body font-semibold">
            {title}
          </h2>
          {description && <p className="mt-px text-small text-ink-2">{description}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

/** A surface on the page. A card of rows divides them with lines; cards never nest. */
export function Card({ rows = false, children }: { rows?: boolean; children: ReactNode }) {
  return <div className={cx("min-w-0 overflow-hidden rounded-lg border border-line bg-surface", rows && "divide-y divide-line")}>{children}</div>;
}

/** A square for the icon that leads a row. */
export function Tile({ tone = "neutral", children }: { tone?: "neutral" | "danger"; children: ReactNode }) {
  return (
    <span aria-hidden="true" className={cx("grid size-10 flex-none place-items-center rounded-md [&_svg]:size-4", tone === "danger" ? "bg-danger-soft text-danger" : "bg-hover text-ink-2")}>
      {children}
    </span>
  );
}

/**
 * What it is on the left, its control on the right. Settings and lists are both rows.
 * With `below`, the control takes the row's width under the text, as a text area does.
 */
export function Row({
  title,
  description,
  leading,
  htmlFor,
  mono = false,
  wide = false,
  below,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  leading?: ReactNode;
  /** The control this row names, so that its title is the control's label. */
  htmlFor?: string;
  mono?: boolean;
  /** The control is wide, as a select is: it has a width of its own, and goes under the text on a phone. */
  wide?: boolean;
  below?: ReactNode;
  children?: ReactNode;
}) {
  const Title = htmlFor ? "label" : "div";
  return (
    <div className="flex flex-col gap-3 p-4">
      <div className={cx("flex min-h-6 gap-4", wide ? "flex-col sm:flex-row sm:items-center" : "items-center")}>
        {leading}
        <div className="min-w-0 flex-1">
          <Title {...(htmlFor ? { htmlFor } : {})} className={cx("flex items-center gap-2 text-body font-semibold", mono && "font-mono", htmlFor && "cursor-pointer")}>
            {title}
          </Title>
          {description && <p className="mt-px text-small text-ink-2">{description}</p>}
        </div>
        {wide ? <div className="flex min-w-0 items-center gap-2 sm:w-72 sm:flex-none sm:justify-end">{children}</div> : children}
      </div>
      {below}
    </div>
  );
}

/** A circle with the user's initial. */
export function Avatar({ name }: { name: string }) {
  return (
    <span aria-hidden="true" className="grid size-7 flex-none place-items-center rounded-full bg-accent-soft text-caption font-semibold text-accent">
      {name.trim().charAt(0).toUpperCase()}
    </span>
  );
}
