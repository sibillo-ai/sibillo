// The one large button of hands-free mode: a whole area to press, that a stray touch does not miss
// (UX-005, UX-037, ADR-0111).
import type { ComponentProps } from "react";

import { cx } from "./cx";

type VoiceButtonProps = Omit<ComponentProps<"button">, "className" | "type"> & {
  /** A press ends what is going on, such as the turn being spoken: the one accent of the screen. */
  active?: boolean;
};

/** It fills what holds it; its icon, large, stands above its words. */
export function VoiceButton({ active = false, children, ...rest }: VoiceButtonProps) {
  return (
    <button
      type="button"
      className={cx(
        "flex w-full flex-1 cursor-pointer flex-col items-center justify-center gap-4 rounded-lg text-title font-semibold transition-[background-color,scale] duration-120 ease-soft active:scale-[0.99] disabled:cursor-wait disabled:active:scale-100 [&_svg]:size-16 [&_svg]:flex-none",
        active ? "bg-accent text-on-accent hover:bg-accent/90" : "bg-ink text-canvas hover:bg-ink/85",
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

/** One answer to an approval request in hands-free mode: wide and tall, with room between answers, so that a
 * stray touch meant for another misses it (UX-041). */
export function VoiceAnswerButton({ children, ...rest }: Omit<ComponentProps<"button">, "className" | "type">) {
  return (
    <button
      type="button"
      className="flex min-h-20 w-full flex-1 cursor-pointer items-center justify-center rounded-lg border border-line-strong bg-surface px-4 text-title font-semibold text-ink transition-[background-color,scale] duration-120 ease-soft hover:bg-sunken active:scale-[0.99]"
      {...rest}
    >
      {children}
    </button>
  );
}
