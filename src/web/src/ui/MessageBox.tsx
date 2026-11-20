// The message box: a floating surface with the text of a message, what is attached to it, a bar of small
// controls and the one accent button of the design language, which sends (UX-037, ADR-0111).
import { FileText, X } from "lucide-react";
import { type ComponentProps, type DragEvent, type FormEvent, type ReactNode, useId } from "react";

import { IconButton } from "./Button";
import { cx } from "./cx";

/**
 * The box and the caption under it. Its children are, from the top: the attachments, the text, and the bar.
 * Files may be dropped on it; `dropping` shows that it would take them.
 */
export function MessageBox({
  onSubmit,
  dropping = false,
  onDragOver,
  onDragLeave,
  onDrop,
  caption,
  children,
}: {
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  dropping?: boolean;
  onDragOver?: (event: DragEvent<HTMLFormElement>) => void;
  onDragLeave?: (event: DragEvent<HTMLFormElement>) => void;
  onDrop?: (event: DragEvent<HTMLFormElement>) => void;
  /** One line under the box, such as where the messages go. */
  caption?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="w-full min-w-0">
      <form
        onSubmit={onSubmit}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={cx(
          "flex flex-col gap-2 rounded-lg border bg-surface p-3 shadow-float transition-colors duration-120 ease-soft",
          dropping ? "border-accent" : "border-line-strong focus-within:border-ink-3",
        )}
      >
        {children}
      </form>
      <p className="mt-2 flex min-h-4 items-center justify-center gap-1 text-center text-caption font-medium text-ink-3 [&_svg]:size-3 [&_svg]:flex-none">{caption}</p>
    </div>
  );
}

/** The text of the message: it has no border of its own, and grows with what is written in it. */
export function MessageInput({ label, id, ...rest }: Omit<ComponentProps<"textarea">, "className" | "aria-label"> & { label: string }) {
  const own = useId();
  return (
    <>
      <label className="sr-only" htmlFor={id ?? own}>
        {label}
      </label>
      <textarea
        id={id ?? own}
        rows={1}
        className="max-h-56 resize-none bg-transparent px-2 py-1 text-reading text-ink outline-none placeholder:text-ink-3 md:min-h-13"
        {...rest}
      />
    </>
  );
}

/** The bar of small controls under the text: ghost buttons at the start; the model and the send button at the end. */
export function MessageBar({ start, end }: { start?: ReactNode; end?: ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-1">
      {start}
      <span className="flex-1" />
      {end}
    </div>
  );
}

/**
 * The round accent button: it sends the message, and stops the answer while one streams. The one place where
 * the accent is a button; its icon is its child.
 */
export function SendButton({ label, type = "submit", children, ...rest }: Omit<ComponentProps<"button">, "className" | "aria-label"> & { label: string }) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      // Pressed, it leaves the focus in the message box, and a phone's keyboard open (UX-018).
      onMouseDown={(event) => event.preventDefault()}
      className="grid size-8 flex-none cursor-pointer place-items-center rounded-full bg-accent text-on-accent transition-[opacity,scale] duration-120 ease-soft hover:opacity-90 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-45 disabled:active:scale-100 pointer-coarse:size-11 [&_svg]:size-4 [&_svg]:flex-none"
      {...rest}
    >
      {children}
    </button>
  );
}

/** The files and images attached to the message, before it is sent. */
export function Attachments({ label, children }: { label: string; children: ReactNode }) {
  return (
    <ul aria-label={label} className="flex flex-wrap gap-2">
      {children}
    </ul>
  );
}

/** One attached file: a small preview when it is an image, its name, its size or how far its upload is, and a button that removes it. */
export function Attachment({
  name,
  preview,
  detail,
  failed = false,
  removeLabel,
  onRemove,
}: {
  name: string;
  /** The address of a preview, for an image. */
  preview?: string | undefined;
  detail: ReactNode;
  /** The detail is an error. */
  failed?: boolean;
  removeLabel: string;
  onRemove: () => void;
}) {
  return (
    <li className="flex max-w-full items-center gap-2 rounded-md border border-line bg-hover py-1 pr-1 pl-2 text-small">
      {preview ? <img src={preview} alt={name} className="size-8 flex-none rounded-sm object-cover" /> : <FileText className="size-4 flex-none text-ink-2" aria-hidden="true" />}
      <span className="flex min-w-0 flex-col">
        <span className="truncate font-semibold">{name}</span>
        <span className={failed ? "text-danger" : "text-ink-2"}>{detail}</span>
      </span>
      <IconButton label={removeLabel} onClick={onRemove}>
        <X aria-hidden="true" />
      </IconButton>
    </li>
  );
}
