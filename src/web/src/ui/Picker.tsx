// A panel that floats beside the button that opened it, with a search and options of two lines, as the model
// picker is (UX-015, ADR-0111).
import { Check } from "lucide-react";
import type { CSSProperties, ReactNode, Ref } from "react";

/** The panel. Where it floats is worked out by what opens it, and given as `style`. */
export function PickerPanel({
  ref,
  label,
  style,
  header,
  footer,
  children,
}: {
  ref?: Ref<HTMLDivElement>;
  label: string;
  style: CSSProperties;
  header?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div ref={ref} role="dialog" aria-label={label} style={style} className="slide fixed z-50 flex flex-col overflow-hidden rounded-md border border-line bg-raised text-ink shadow-float">
      {header && <div className="border-b border-line p-2">{header}</div>}
      <div className="min-h-0 overflow-y-auto p-1">{children}</div>
      {footer && <p className="border-t border-line px-3 py-2 text-caption text-ink-3">{footer}</p>}
    </div>
  );
}

/** A group of options under a heading, with a note for all of them. */
export function PickerGroup({ icon, title, end, note, children }: { icon?: ReactNode; title: string; end?: ReactNode; note?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <h3 className="flex items-center gap-1 px-2 pt-3 pb-1 text-caption font-medium text-ink-3 [&_svg]:size-3">
        {icon}
        {title}
        {end && <span className="ml-auto font-normal">{end}</span>}
      </h3>
      {note && <p className="px-2 pb-1 text-caption text-ink-2">{note}</p>}
      {children}
    </section>
  );
}

/** One option: its name with its badges, a line of detail below, and a mark when it is the chosen one. */
export function PickerOption({
  title,
  badges,
  detail,
  chosen = false,
  disabled = false,
  onPick,
}: {
  title: string;
  badges?: ReactNode;
  detail?: ReactNode;
  chosen?: boolean;
  disabled?: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onPick}
      className="flex w-full cursor-pointer items-center gap-2 rounded-sm px-2 py-2 text-left transition-colors duration-120 hover:bg-hover focus-visible:bg-hover disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent"
    >
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2 text-body font-semibold">
          <span className="truncate">{title}</span>
          {badges}
        </span>
        {detail && <span className="block text-small text-ink-2 tabular-nums">{detail}</span>}
      </span>
      {chosen && <Check className="size-4 flex-none text-accent" aria-hidden="true" />}
    </button>
  );
}

/** What a picker says when nothing matches. */
export function PickerEmpty({ children }: { children: ReactNode }) {
  return <p className="px-2 py-4 text-body text-ink-2">{children}</p>;
}
