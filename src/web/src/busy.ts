// Actions of the user that show that they are in progress and run once at a time (UX-038, ADR-0111).
import { useCallback, useRef, useState } from "react";

/**
 * Runs an action of the user under a key, ignoring the same key while it is in progress:
 * a second press, or a press that arrives before the button is drawn as busy, sends nothing.
 * `busy(key)` says whether it is in progress, for the button's busy state.
 */
export function useBusy() {
  const running = useRef(new Set<string>());
  const [, redraw] = useState(0);
  const run = useCallback(async (key: string, work: () => Promise<unknown>): Promise<void> => {
    if (running.current.has(key)) return;
    running.current.add(key);
    redraw((count) => count + 1);
    try {
      await work();
    } finally {
      running.current.delete(key);
      redraw((count) => count + 1);
    }
  }, []);
  const busy = (key: string) => running.current.has(key);
  return { busy, run };
}
