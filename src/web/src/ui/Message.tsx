// The parts of a conversation's thread: a user's message and an answer, the actions under them, what a run did
// as steps that expand (UX-003), and the small cards shown where something happened (UX-037, ADR-0111).
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { Tile } from "./Card";
import { cx } from "./cx";

/** One run of the thread: the user's message and what answered it. Its actions show when it is pointed at. */
export function Turn({ children }: { children: ReactNode }) {
  return <li className="group/turn flex min-w-0 flex-col gap-3">{children}</li>;
}

/** The user's message with the actions under it, at the end of the column. */
export function UserMessage({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="group/message flex min-w-0 flex-col items-end gap-1">
      {children}
      {actions}
    </div>
  );
}

/** What the user said: a bubble at the end of the column, four fifths of it at most. */
export function Bubble({ speaker, children }: { speaker: string; children: ReactNode }) {
  return (
    <div className="max-w-4/5 self-end rounded-lg rounded-br-sm border border-line bg-sunken px-4 py-3 text-reading break-words whitespace-pre-wrap">
      <span className="sr-only">{speaker}: </span>
      {children}
    </div>
  );
}

/** The files sent with a message, above its bubble. */
export function Attachments({ label, children }: { label: string; children: ReactNode }) {
  return (
    <ul aria-label={label} className="flex max-w-4/5 flex-wrap justify-end gap-2 self-end">
      {children}
    </ul>
  );
}

/** An attached file, by its name and its size: pressed, it shows the file. */
export function AttachmentChip({ icon, name, detail, onShow }: { icon: ReactNode; name: ReactNode; detail: ReactNode; onShow: () => void }) {
  return (
    <button
      type="button"
      onClick={onShow}
      className="flex max-w-64 cursor-pointer items-center gap-2 rounded-md border border-line bg-surface px-3 py-2 text-left text-small transition-colors duration-120 hover:bg-hover pointer-coarse:min-h-11 [&_svg]:size-4 [&_svg]:flex-none [&_svg]:text-ink-2"
    >
      {icon}
      <span className="flex min-w-0 flex-col">
        <span className="truncate font-semibold">{name}</span>
        <span className="text-caption text-ink-2">{detail}</span>
      </span>
    </button>
  );
}

/** An attached image, as a small preview: pressed, it shows the file. */
export function AttachmentImage({ src, alt, onShow }: { src: string; alt: string; onShow: () => void }) {
  return (
    <button type="button" onClick={onShow} className="block cursor-pointer overflow-hidden rounded-md border border-line transition-opacity duration-120 hover:opacity-90">
      <img src={src} alt={alt} loading="lazy" className="max-h-40 max-w-56 object-cover" />
    </button>
  );
}

/** The answer: plain text in the reading role, with what the run did where it happened. */
export function AnswerBody({ children }: { children: ReactNode }) {
  return <div className="flex min-w-0 flex-col gap-3 text-reading">{children}</div>;
}

const REVEAL = {
  message: "group-hover/message:opacity-100 group-focus-within/message:opacity-100",
  turn: "group-hover/turn:opacity-100 group-focus-within/turn:opacity-100",
};

/**
 * The row of small actions under a message: icon buttons, then a caption that is always in view.
 * The buttons show when their message, or their turn, is pointed at or holds the focus; always where
 * nothing hovers, as on a touch screen, and when `shown`.
 */
export function MessageActions({
  reveal,
  shown = false,
  caption,
  children,
}: {
  reveal: keyof typeof REVEAL;
  shown?: boolean;
  caption?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={cx("flex items-center", reveal === "message" ? "-mr-2" : "-ml-2")}>
      <div className={cx("flex items-center gap-px transition-opacity duration-120 [@media(hover:none)]:opacity-100", shown ? "opacity-100" : "opacity-0", REVEAL[reveal])}>
        {children}
      </div>
      {caption && <span className="ml-2 text-caption text-ink-3 tabular-nums">{caption}</span>}
    </div>
  );
}

/** The sprite, and beside it what it acts out, in words. */
export function SpriteLine({ sprite, children }: { sprite: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex min-h-14 items-center gap-3">
      {sprite}
      {children}
    </div>
  );
}

/** What a run did, as one block of steps (UX-003). */
export function Steps({ children }: { children: ReactNode }) {
  return <div className="max-w-full min-w-0 divide-y divide-line overflow-hidden rounded-md border border-line bg-surface">{children}</div>;
}

/**
 * One step: a line as wide as its block with an icon, a verb and a caption, that opens its details.
 * With `stacked`, the caption is a line of its own under the verb, as a command's first line is.
 */
export function Step({
  icon,
  verb,
  caption,
  stacked = false,
  end,
  children,
}: {
  /** The step's icon or state, with its words for assistive technologies. */
  icon?: ReactNode;
  verb: ReactNode;
  caption?: ReactNode;
  stacked?: boolean;
  /** What stands at the end of the line, such as how the step was decided. */
  end?: ReactNode;
  children: ReactNode;
}) {
  return (
    <details className="group/step min-w-0">
      <summary className="flex min-h-10 w-full cursor-pointer list-none items-center gap-2 px-3 py-2 text-small text-ink-2 transition-colors duration-120 hover:bg-hover focus-visible:-outline-offset-2 pointer-coarse:min-h-11 [&::-webkit-details-marker]:hidden [&>svg]:size-4 [&>svg]:flex-none">
        {icon}
        <span className={cx("flex min-w-0 flex-1", stacked ? "flex-col" : "items-center gap-2")}>
          <b className="truncate font-medium text-ink">{verb}</b>
          {caption && <span className="min-w-0 truncate font-mono text-caption">{caption}</span>}
        </span>
        {end}
        <ChevronRight className="text-ink-3 transition-transform duration-120 group-open/step:rotate-90" aria-hidden="true" />
      </summary>
      <div className="flex min-w-0 flex-col gap-2 border-t border-line p-3 text-small text-ink-2">{children}</div>
    </details>
  );
}

/** A part of a step's details under its heading: what a call was given, or what it returned. */
export function StepDetail({ title, tall = false, children }: { title: string; tall?: boolean; children: ReactNode }) {
  return (
    <>
      <p className="font-semibold">{title}</p>
      <pre className={cx("rounded-sm bg-hover p-2 font-mono text-caption text-ink", tall ? "max-h-80 overflow-auto whitespace-pre-wrap" : "overflow-x-auto")}>{children}</pre>
    </>
  );
}

/** A small card in the thread, where something happened: what it was, the way to its page, and what it holds. */
export function ThreadCard({
  label,
  icon,
  link,
  mono = false,
  children,
}: {
  /** What happened: the card's heading, and its name for assistive technologies. */
  label: string;
  icon: ReactNode;
  link?: ReactNode;
  mono?: boolean;
  children: ReactNode;
}) {
  return (
    <div role="group" aria-label={label} className="flex w-full max-w-120 items-start gap-3 rounded-md border border-line bg-surface p-3">
      <Tile>{icon}</Tile>
      <div className="flex min-w-0 flex-1 flex-col gap-px">
        <div className="flex items-center justify-between gap-2">
          <b className="text-small font-semibold">{label}</b>
          {link}
        </div>
        <span className={cx("text-small text-ink-2", mono ? "font-mono break-all" : "break-words")}>{children}</span>
      </div>
    </div>
  );
}

/** A file in the thread: its name shows it, and its action, a shared button, is at the end. */
export function FileCard({
  icon,
  name,
  detail,
  gone = false,
  hint,
  onShow,
  action,
}: {
  icon: ReactNode;
  name: string;
  detail: ReactNode;
  /** The file is no longer there: its detail says so. */
  gone?: boolean;
  /** What pressing the name does, as a tooltip. */
  hint: string;
  onShow: () => void;
  action: ReactNode;
}) {
  return (
    <div role="group" aria-label={name} className="flex w-full max-w-96 items-center gap-3 rounded-md border border-line bg-surface p-3">
      <Tile>{icon}</Tile>
      <button type="button" onClick={onShow} title={hint} className="flex min-w-0 flex-1 cursor-pointer flex-col rounded-sm text-left">
        <span className="truncate text-body font-semibold">{name}</span>
        <span className={cx("text-caption", gone ? "text-danger" : "text-ink-3")}>{detail}</span>
      </button>
      {action}
    </div>
  );
}

/** Why a run failed, where its answer would be: what happened, what to do, and what the model said (UX-014). */
export function ErrorCard({ sprite, title, reason, children }: { sprite: ReactNode; title: string; reason?: ReactNode; children: ReactNode }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-danger/45 bg-surface p-3">
      {sprite}
      <div className="min-w-0 flex-1 text-body">
        <strong className="block font-semibold">{title}</strong>
        <p className="mt-px text-ink-2">{children}</p>
        {reason && <blockquote className="mt-2 border-l-2 border-line-strong pl-3 break-words whitespace-pre-wrap">{reason}</blockquote>}
      </div>
    </div>
  );
}
