// Side panels the user resizes by their edge, or with the keyboard (UX-021).
import { type KeyboardEvent, type PointerEvent, useCallback, useRef, useState } from "react";

const STEP = 16;

export interface PanelWidth {
  width: number;
  min: number;
  max: number;
  change: (width: number) => void;
  reset: () => void;
}

/** A panel's width, kept on the device; what was kept is ignored when it is out of bounds. */
export function usePanelWidth(key: string, initial: number, min: number, max: number): PanelWidth {
  const read = () => {
    try {
      const kept = Number(localStorage.getItem(key));
      return kept >= min && kept <= max ? kept : initial;
    } catch {
      return initial;
    }
  };
  const [width, setWidth] = useState(read);
  const change = useCallback(
    (next: number) => {
      const bounded = Math.round(Math.min(max, Math.max(min, next)));
      setWidth(bounded);
      try {
        localStorage.setItem(key, String(bounded));
      } catch {
        // Kept for this page only.
      }
    },
    [key, min, max],
  );
  const reset = useCallback(() => {
    setWidth(initial);
    try {
      localStorage.removeItem(key);
    } catch {
      // Nothing was kept.
    }
  }, [key, initial]);
  return { width, min, max, change, reset };
}

/**
 * The edge of a panel: dragged, or moved with the arrow keys, it resizes the panel; a double click
 * brings back its default width. `side` is where the edge is on the panel: its start or its end, which
 * are its left and its right in a language written from left to right, and the other way round in one
 * written from right to left (I18N-005).
 */
export function ResizeHandle({ label, side, panel, className = "" }: { label: string; side: "start" | "end"; panel: PanelWidth; className?: string }) {
  const drag = useRef<{ x: number; width: number; direction: number } | null>(null);

  /** Moving the edge away from the panel widens it: +1 when that is towards the right of the screen. */
  function direction(element: HTMLElement): number {
    const rightToLeft = getComputedStyle(element).direction === "rtl";
    return (side === "end") !== rightToLeft ? 1 : -1;
  }

  function down(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, width: panel.width, direction: direction(event.currentTarget) };
  }

  function move(event: PointerEvent<HTMLDivElement>) {
    if (drag.current === null) return;
    panel.change(drag.current.width + drag.current.direction * (event.clientX - drag.current.x));
  }

  function up(event: PointerEvent<HTMLDivElement>) {
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function key(event: KeyboardEvent<HTMLDivElement>) {
    const sign = direction(event.currentTarget);
    const moves: Record<string, number> = { ArrowLeft: -STEP * sign, ArrowRight: STEP * sign };
    if (event.key in moves) panel.change(panel.width + (moves[event.key] ?? 0));
    else if (event.key === "Home") panel.change(panel.min);
    else if (event.key === "End") panel.change(panel.max);
    else return;
    event.preventDefault();
  }

  return (
    <div
      role="separator"
      aria-label={label}
      aria-orientation="vertical"
      aria-valuenow={panel.width}
      aria-valuemin={panel.min}
      aria-valuemax={panel.max}
      tabIndex={0}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
      onKeyDown={key}
      onDoubleClick={panel.reset}
      className={`absolute inset-y-0 z-10 w-2 cursor-col-resize touch-none outline-none after:absolute after:inset-y-0 after:inset-x-0 after:mx-auto after:w-0.5 after:transition-colors hover:after:bg-accent focus-visible:after:bg-accent ${side === "end" ? "-end-1" : "-start-1"} ${className}`}
    />
  );
}
