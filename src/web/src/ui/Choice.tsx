// Choices of the design language: on or off, one of a few, one of several (UX-037, ADR-0111).
import { type ComponentProps, type ReactNode, useId } from "react";

import { cx } from "./cx";

/** On or off. Ink when on: the accent is kept for the one thing to do next. */
export function Switch({
  checked,
  onChange,
  ...rest
}: Omit<ComponentProps<"input">, "className" | "type" | "role" | "checked" | "onChange"> & { checked: boolean; onChange: (on: boolean) => void }) {
  return (
    <span className="relative inline-flex flex-none">
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        onChange={(event) => onChange(event.currentTarget.checked)}
        className="peer absolute -inset-2 cursor-pointer opacity-0 disabled:cursor-not-allowed"
        {...rest}
      />
      <span
        aria-hidden="true"
        className="pointer-events-none h-5 w-9 rounded-full bg-line-strong transition-colors duration-200 ease-soft peer-checked:bg-ink peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent peer-disabled:opacity-45 after:absolute after:top-0.5 after:start-0.5 after:size-4 after:rounded-full after:bg-surface after:shadow-line after:transition-transform after:duration-200 after:ease-soft peer-checked:after:translate-x-4 rtl:peer-checked:after:-translate-x-4 peer-checked:after:bg-canvas"
      />
    </span>
  );
}

const SEGMENTS = "inline-flex h-10 max-w-full flex-none gap-0.5 rounded-md bg-hover p-0.5";
const SEGMENT = "flex items-center rounded-sm px-4 text-small font-medium whitespace-nowrap text-ink-2 transition-colors duration-120";

/** One of a few, all in view. */
export function Segmented<T extends string>({
  label,
  labelledBy,
  describedBy,
  options,
  value,
  onChange,
  disabled = false,
}: {
  /** What is being chosen, for assistive technologies: its name, or the element that names it. */
  label?: string;
  labelledBy?: string;
  describedBy?: string;
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  const name = useId();
  return (
    <div
      role="radiogroup"
      aria-label={label}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      aria-disabled={disabled || undefined}
      className={cx(SEGMENTS, disabled && "opacity-45")}
    >
      {options.map((option) => (
        <label key={option.value} className="relative flex">
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={option.value === value}
            disabled={disabled}
            onChange={() => onChange(option.value)}
            className="peer absolute inset-0 cursor-pointer opacity-0 disabled:cursor-not-allowed"
          />
          <span className={cx(SEGMENT, "pointer-events-none peer-checked:bg-surface peer-checked:font-semibold peer-checked:text-ink peer-checked:shadow-line peer-focus-visible:outline-2 peer-focus-visible:outline-accent")}>
            {option.label}
          </span>
        </label>
      ))}
    </div>
  );
}

/** One of a few views or kinds, all in view: buttons, of which the pressed one is the choice. */
export function ToggleGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className={SEGMENTS}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          className={cx(SEGMENT, "cursor-pointer aria-pressed:bg-surface aria-pressed:font-semibold aria-pressed:text-ink aria-pressed:shadow-line")}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** Any of several. */
export function Checkbox(props: Omit<ComponentProps<"input">, "className" | "type">) {
  return (
    <input
      type="checkbox"
      className="size-4 flex-none cursor-pointer appearance-none rounded-sm border border-line-strong bg-surface bg-center bg-no-repeat transition-colors duration-120 checked:border-ink checked:bg-ink checked:bg-[image:var(--check)] disabled:cursor-not-allowed disabled:opacity-45"
      {...props}
    />
  );
}

/** One of several, each with room for a description beside it. */
export function Radio(props: Omit<ComponentProps<"input">, "className" | "type">) {
  return (
    <input
      type="radio"
      className="size-4 flex-none cursor-pointer appearance-none rounded-full border border-line-strong bg-surface transition-[border-width,border-color] duration-120 checked:border-5 checked:border-ink disabled:cursor-not-allowed disabled:opacity-45"
      {...props}
    />
  );
}

/** A short state beside a name. */
export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "ok" | "warn" | "danger" | "accent"; children: ReactNode }) {
  const tones = { neutral: "bg-hover text-ink-2", ok: "bg-ok-soft text-ok", warn: "bg-warn-soft text-warn", danger: "bg-danger-soft text-danger", accent: "bg-accent-soft text-accent" };
  return <span className={cx("inline-flex h-5 flex-none items-center gap-1 rounded-sm px-2 text-caption font-medium whitespace-nowrap [&_svg]:size-3", tones[tone])}>{children}</span>;
}
