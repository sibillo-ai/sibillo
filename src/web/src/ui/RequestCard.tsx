// What waits above the message box, or in its place: the card of an approval or a question, and the list of
// the steps of a long task (UX-009, UX-022, UX-037, ADR-0111).
import { ChevronLeft, ChevronRight } from "lucide-react";
import { type ReactNode, useId } from "react";

import { IconButton } from "./Button";
import { Checkbox, Radio } from "./Choice";
import { cx } from "./cx";

/** A button that moves between the requests of a card. */
type Move = { label: string; disabled: boolean; onClick: () => void };

/**
 * A request of the assistant: a region named by its title, a body that scrolls when it is long, and a footer
 * of buttons that stays in view, the action last.
 */
export function RequestCard({
  icon,
  title,
  step,
  tall = false,
  footer,
  footerStart,
  children,
}: {
  icon: ReactNode;
  title: string;
  /** Which of several requests is shown, and the buttons that move between them when the user may. */
  step?: { text: string; previous?: Move; next?: Move } | undefined;
  /** The card may take more of the window's height, as one with much to read does. */
  tall?: boolean;
  /** The buttons, the action last. */
  footer: ReactNode;
  /**
   * What stands apart at the start of the footer, such as the answers that last longer than this once. It is
   * shown first and comes last for the keyboard and for assistive technologies.
   */
  footerStart?: ReactNode;
  children: ReactNode;
}) {
  const heading = useId();
  return (
    <section
      aria-labelledby={heading}
      className={cx("flex flex-col rounded-lg border border-line-strong bg-surface shadow-float", tall ? "max-h-[min(70dvh,38rem)]" : "max-h-[min(60dvh,34rem)]")}
    >
      <header className="flex min-h-8 flex-none items-center gap-2 px-4 pt-3 [&>svg]:size-4 [&>svg]:flex-none">
        {icon}
        <h2 id={heading} className="min-w-0 flex-1 text-small font-semibold">
          {title}
        </h2>
        {step && (
          <>
            <span className="text-caption font-medium text-ink-3 tabular-nums" aria-live="polite">
              {step.text}
            </span>
            {step.previous && (
              <IconButton label={step.previous.label} disabled={step.previous.disabled} onClick={step.previous.onClick}>
                <ChevronLeft aria-hidden="true" />
              </IconButton>
            )}
            {step.next && (
              <IconButton label={step.next.label} disabled={step.next.disabled} onClick={step.next.onClick}>
                <ChevronRight aria-hidden="true" />
              </IconButton>
            )}
          </>
        )}
      </header>
      <div className="min-h-0 overflow-y-auto px-4 py-3">{children}</div>
      <footer className="flex flex-none flex-wrap items-center justify-end gap-2 border-t border-line px-4 py-3">
        {footer}
        {footerStart && <div className="ml-auto flex flex-wrap items-center gap-2">{footerStart}</div>}
      </footer>
    </section>
  );
}

/** Choices, as rows of one bordered list. */
export function ChoiceList({ children }: { children: ReactNode }) {
  return <div className="flex flex-col divide-y divide-line overflow-hidden rounded-md border border-line">{children}</div>;
}

/** One choice: a radio, or a checkbox when several may be chosen, with its title and a description. */
export function ChoiceRow({
  several = false,
  name,
  checked,
  onChange,
  title,
  description,
}: {
  several?: boolean;
  name: string;
  checked: boolean;
  onChange: (on: boolean) => void;
  title: string;
  description?: ReactNode;
}) {
  const Mark = several ? Checkbox : Radio;
  return (
    <label className="flex cursor-pointer items-start gap-3 px-3 py-2 transition-colors duration-120 hover:bg-hover has-checked:bg-hover pointer-coarse:min-h-11 pointer-coarse:py-3">
      <span className="flex h-5 flex-none items-center">
        <Mark name={name} checked={checked} onChange={(event) => onChange(event.currentTarget.checked)} />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="text-body font-semibold">{title}</span>
        {description && <span className="text-small text-ink-2">{description}</span>}
      </span>
    </label>
  );
}

/** Terms and what they are, in two columns: what a call sends, and where. */
export function Facts({ children }: { children: ReactNode }) {
  return <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-body">{children}</dl>;
}

export function Fact({ term, mono = false, children }: { term: string; mono?: boolean; children: ReactNode }) {
  return (
    <>
      <dt className="font-semibold text-ink-2">{term}</dt>
      <dd className={cx("break-words", mono && "font-mono text-small whitespace-pre-wrap")}>{children}</dd>
    </>
  );
}

/** Text as it is, such as a command or the arguments of a call: a block that scrolls when it is long. */
export function CodeBlock({ children }: { children: ReactNode }) {
  return <pre className="max-h-40 overflow-auto rounded-md border border-line bg-surface p-3 font-mono text-small whitespace-pre-wrap">{children}</pre>;
}

/** The steps of a long task under a line that says how far it got (UX-009). */
export function StepList({ summary, label, children }: { summary: string; label: string; children: ReactNode }) {
  return (
    <div className="mb-2 flex flex-col gap-2 rounded-md border border-line bg-surface px-3 py-2">
      <p className="text-caption font-medium text-ink-3">{summary}</p>
      <ul aria-label={label} className="flex max-h-40 flex-col gap-1 overflow-y-auto">
        {children}
      </ul>
    </div>
  );
}

/** One step: the icon of its state, the state in words for assistive technologies, and what the step is. */
export function Step({
  icon,
  state,
  tone = "pending",
  children,
}: {
  icon: ReactNode;
  state: string;
  /** Going on now, still to do, or behind: done or given up. */
  tone?: "going" | "pending" | "past" | "dropped";
  children: ReactNode;
}) {
  return (
    <li className={cx("flex items-start gap-2 text-small [&>svg]:mt-px [&>svg]:size-4 [&>svg]:flex-none", tone === "past" || tone === "dropped" ? "text-ink-2" : "text-ink")}>
      {icon}
      <span className="sr-only">{state}: </span>
      <span className={cx("min-w-0", tone === "dropped" && "line-through", tone === "going" && "live-text font-semibold")}>{children}</span>
    </li>
  );
}
