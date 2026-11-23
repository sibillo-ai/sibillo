// Fields of the design language: one line, several lines, a search and a select, with their label (UX-037, ADR-0111).
import { ChevronDown, CircleAlert, Search } from "lucide-react";
import { type ComponentProps, type ReactNode, useId } from "react";

import { cx } from "./cx";

// 16px text where the pointer is a finger, so that phones do not zoom into the field.
const BOX =
  "w-full rounded-md border border-line-strong bg-surface px-3 text-body text-ink outline-none transition-colors duration-120 placeholder:text-ink-3 hover:border-ink-3 focus:border-accent focus:ring-3 focus:ring-accent-soft disabled:cursor-not-allowed disabled:opacity-45 aria-invalid:border-danger pointer-coarse:min-h-11 pointer-coarse:text-reading";

/** What a field needs to be tied to its label, its hint and its error. */
export type FieldTies = { id: string; "aria-describedby"?: string; "aria-invalid"?: true };

/** A label above a field, and a hint or an error below it. */
export function FormField({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: ReactNode;
  error?: ReactNode;
  children: (ties: FieldTies) => ReactNode;
}) {
  const id = useId();
  const below = `${id}-below`;
  const ties: FieldTies = { id, ...(hint || error ? { "aria-describedby": below } : {}), ...(error ? { "aria-invalid": true as const } : {}) };
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <label htmlFor={id} className="text-small font-semibold">
        {label}
      </label>
      {children(ties)}
      {error ? (
        <p id={below} role="alert" className="flex items-center gap-1 text-small text-danger">
          <CircleAlert className="size-4 flex-none" aria-hidden="true" />
          {error}
        </p>
      ) : (
        hint && (
          <p id={below} className="text-small text-ink-2">
            {hint}
          </p>
        )
      )}
    </div>
  );
}

/** One line of text. */
export function TextInput({ mono = false, ...rest }: Omit<ComponentProps<"input">, "className"> & { mono?: boolean }) {
  return <input className={cx(BOX, "h-10", mono && "font-mono")} {...rest} />;
}

/** Several lines of text. */
export function TextArea({ mono = false, tall = false, ...rest }: Omit<ComponentProps<"textarea">, "className"> & { mono?: boolean; tall?: boolean }) {
  return <textarea className={cx(BOX, "resize-y py-2", tall ? "min-h-64" : "min-h-24", mono && "font-mono")} {...rest} />;
}

/** A search: quiet until it is used. */
export function SearchInput({ label, ...rest }: Omit<ComponentProps<"input">, "className" | "type" | "aria-label"> & { label: string }) {
  return (
    <div className="relative w-full">
      <Search className="pointer-events-none absolute top-1/2 start-2 size-4 -translate-y-1/2 text-ink-3" aria-hidden="true" />
      <input
        type="search"
        aria-label={label}
        placeholder={label}
        className="h-8 w-full rounded-md border border-transparent bg-hover pe-2 ps-8 text-small text-ink outline-none transition-colors duration-120 placeholder:text-ink-3 focus:border-accent focus:bg-surface focus:ring-3 focus:ring-accent-soft pointer-coarse:min-h-11 pointer-coarse:text-reading [&::-webkit-search-cancel-button]:appearance-none"
        {...rest}
      />
    </div>
  );
}

/** A choice among options. It looks like a field on every browser; the list it opens is the device's own. */
export function Select({ children, ...rest }: Omit<ComponentProps<"select">, "className">) {
  return (
    <div className="relative w-full">
      <select className={cx(BOX, "h-10 cursor-pointer appearance-none truncate pe-9")} {...rest}>
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute top-1/2 end-3 size-4 -translate-y-1/2 text-ink-2" aria-hidden="true" />
    </div>
  );
}

/** A button that opens a picker of its own and looks like a select, as the model picker's does (UX-015). */
export function SelectButton({ leading, children, ...rest }: Omit<ComponentProps<"button">, "className" | "type"> & { leading?: ReactNode }) {
  return (
    <button type="button" className={cx(BOX, "flex h-10 cursor-pointer items-center gap-2 text-start aria-expanded:border-accent [&_svg]:size-4 [&_svg]:flex-none")} {...rest}>
      {leading}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      <ChevronDown className="text-ink-2" aria-hidden="true" />
    </button>
  );
}

/** The input behind a button that picks files: never seen, and opened by the button. */
export function FileInput(props: Omit<ComponentProps<"input">, "className" | "type">) {
  return <input type="file" className="sr-only" tabIndex={-1} {...props} />;
}
