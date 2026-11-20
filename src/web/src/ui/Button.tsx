// The one button of the design language (UX-037, ADR-0111).
import { LoaderCircle } from "lucide-react";
import type { ComponentProps } from "react";

import { cx } from "./cx";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "danger-solid";
export type ButtonSize = "md" | "sm";

const BASE =
  "inline-flex cursor-pointer items-center justify-center gap-2 rounded-md border font-semibold whitespace-nowrap transition-[background-color,scale] duration-120 ease-soft active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45 disabled:active:scale-100 aria-busy:cursor-progress aria-busy:opacity-100 pointer-coarse:min-h-11 [&_svg]:size-4 [&_svg]:flex-none";
const VARIANTS: Record<ButtonVariant, string> = {
  primary: "border-ink bg-ink text-canvas hover:bg-ink/85",
  secondary: "border-line-strong bg-surface text-ink hover:bg-sunken",
  ghost: "border-transparent text-ink hover:bg-hover",
  danger: "border-line-strong bg-surface text-danger hover:bg-danger-soft",
  "danger-solid": "border-danger bg-danger text-on-accent hover:bg-danger/85",
};
const SIZES: Record<ButtonSize, string> = { md: "h-10 px-4 text-body", sm: "h-8 px-3 text-small" };
const SQUARES: Record<ButtonSize, string> = { md: "size-10 text-body pointer-coarse:min-w-11", sm: "size-8 text-small pointer-coarse:min-w-11" };

/** The classes of a button, for what must look like one and is not a `<button>`, such as a link. */
export function buttonClass({
  variant = "secondary",
  size = "md",
  square = false,
  block = false,
  shrink = false,
}: { variant?: ButtonVariant; size?: ButtonSize; square?: boolean; block?: boolean; shrink?: boolean } = {}): string {
  return cx(BASE, shrink ? "min-w-0 shrink" : "flex-none", VARIANTS[variant], square ? SQUARES[size] : SIZES[size], block && "w-full");
}

type ButtonProps = Omit<ComponentProps<"button">, "className"> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Stretch to the width of what holds it. */
  block?: boolean;
  /** Give way when there is no room, cutting the text short: wrap the text in a truncating element. */
  shrink?: boolean;
  /** The action is in progress: the button shows it and cannot start it twice (UX-038). */
  busy?: boolean;
};

/** Primary once per view at most; secondary otherwise; ghost in toolbars; danger for what cannot be undone. */
export function Button({ variant = "secondary", size = "md", block = false, shrink = false, busy = false, disabled, type = "button", children, ...rest }: ButtonProps) {
  return (
    <button type={type} disabled={disabled || busy} aria-busy={busy || undefined} className={buttonClass({ variant, size, block, shrink })} {...rest}>
      {busy && <LoaderCircle className="animate-spin" aria-hidden="true" />}
      {children}
    </button>
  );
}

type IconButtonProps = Omit<ComponentProps<"button">, "className" | "aria-label"> & {
  /** What the button does, for assistive technologies and as a tooltip. */
  label: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
};

/** A button that shows an icon alone. */
export function IconButton({ label, variant = "ghost", size = "sm", type = "button", children, ...rest }: IconButtonProps) {
  return (
    <button type={type} aria-label={label} title={label} className={buttonClass({ variant, size, square: true })} {...rest}>
      {children}
    </button>
  );
}
