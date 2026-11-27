// The stream of the user's changes (API-008, UX-032, ADR-0108): what it announces is shown at once, such as a
// conversation a task started, marked as running until its run ends, or a title (ADR-0146).
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useSyncExternalStore } from "react";

import { API_BASE, type Schemas } from "./api/client";
import { CONVERSATIONS } from "./conversations";

type ChangeEvent = Schemas["ChangeEvent"];

const KINDS = ["conversation_created", "conversation_titled", "run_started", "run_finished", "task_fired"] as const;

// The conversations with a run in progress, as the stream announced them.
let running = new Set<string>();
const listeners = new Set<() => void>();

function setRunning(conversation: string, on: boolean) {
  if (running.has(conversation) === on) return;
  running = new Set(running);
  if (on) running.add(conversation);
  else running.delete(conversation);
  for (const listener of listeners) listener();
}

/** The conversations whose run the stream says is in progress. */
export function useRunning(): ReadonlySet<string> {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => running,
  );
}

/** Follow the stream while the app is open; after it is lost, reload what the app shows. */
export function useChangeStream() {
  const queries = useQueryClient();
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const source = new EventSource(`${API_BASE}/me/events`);
    let lost = false;
    const refresh = () => {
      void queries.invalidateQueries({ queryKey: CONVERSATIONS });
      void queries.invalidateQueries({ queryKey: ["tasks"] });
    };
    const received = (message: MessageEvent<string>) => {
      let change: ChangeEvent;
      try {
        change = JSON.parse(message.data) as ChangeEvent;
      } catch {
        return;
      }
      if (change.type === "run_started" && change.conversation_id) setRunning(change.conversation_id, true);
      if (change.type === "run_finished" && change.conversation_id) {
        setRunning(change.conversation_id, false);
        void queries.invalidateQueries({ queryKey: ["conversation", change.conversation_id] });
      }
      // A title can arrive after the run that asked for it (ADR-0146).
      if (change.type === "conversation_titled" && change.conversation_id) {
        void queries.invalidateQueries({ queryKey: ["conversation", change.conversation_id, "details"] });
      }
      refresh();
    };
    for (const kind of KINDS) source.addEventListener(kind, received);
    source.onerror = () => {
      lost = true;
    };
    source.onopen = () => {
      if (!lost) return;
      lost = false;
      running = new Set();
      for (const listener of listeners) listener();
      refresh();
    };
    return () => source.close();
  }, [queries]);
}
