// What the assistant remembers about the user (MEM-001 to MEM-008, UX-027, ADR-0095).
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api/client";

export const MEMORY = ["me", "memory"] as const;
// The settings section that shows it, as a link names it.
export const MEMORY_SECTION = "/settings?section=memory";

export function useMemory() {
  return useQuery({ queryKey: MEMORY, queryFn: async () => unwrap(await api.GET("/me/memory")) });
}

export type MemoryChange = "remember" | "update_memory" | "forget";

/** A memory tool's call that changed memory, as its result says; null for any other call, or one that failed. */
export function memoryChangeOf(name: string, result: string | undefined): MemoryChange | null {
  if (result === undefined) return null;
  if (name === "remember" && result.startsWith("Remembered")) return "remember";
  if (name === "update_memory" && result.startsWith("Changed")) return "update_memory";
  if (name === "forget" && result.startsWith("Forgot")) return "forget";
  return null;
}
