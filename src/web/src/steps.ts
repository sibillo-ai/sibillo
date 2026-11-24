// A run's steps in compact lines: the argument a step's line previews, how a block folds, and what its folded line
// counts (UX-043, ADR-0140).
import i18n from "./i18n";

/** The argument that tells a call of each tool apart; any other tool shows its first argument that is a string. */
const TELLING: Record<string, string> = {
  web_search: "query",
  read_page: "url",
  browser_goto: "url",
  browser_download: "url",
  browser_fill: "value",
  browser_select_option: "value",
  browser_press: "key",
  browser_wait_for_state: "state",
  browser_find_element: "name",
  browser_call_page_tool: "name",
};
/** Tools whose argument is a script or a schema: nothing of it is shown in the line. */
const UNSHOWN = new Set(["browser_evaluate", "browser_run", "browser_extract"]);
/** Commands show their first line. */
const COMMANDS = new Set(["run_command", "start_command"]);
/** An address longer than this shows by its host. */
const LONG_ADDRESS = 60;
/** How many of a block's steps show while the run works. */
const LAST_STEPS = 3;

/** What a step's line shows of its call's arguments, after its label. */
export function previewOf(name: string, args: Record<string, unknown>): string {
  if (UNSHOWN.has(name)) return "";
  if (COMMANDS.has(name)) return typeof args.command === "string" ? (args.command.split("\n")[0] ?? "") : "";
  const named = TELLING[name];
  const value = named !== undefined ? args[named] : Object.values(args).find((item) => typeof item === "string");
  if (typeof value !== "string") return "";
  if (named === "url" && value.length > LONG_ADDRESS) {
    try {
      return new URL(value).host;
    } catch {
      return value;
    }
  }
  return value;
}

/** Which of a block's steps show: all of a short or opened block; the last three while the run works; none once it ended. */
export function folded<T>(steps: T[], { running, open }: { running: boolean; open: boolean }): { hidden: number; shown: T[] } {
  if (open || steps.length <= LAST_STEPS) return { hidden: 0, shown: steps };
  if (running) return { hidden: steps.length - LAST_STEPS, shown: steps.slice(-LAST_STEPS) };
  return { hidden: steps.length, shown: [] };
}

/** Each label of a block's steps, with how many steps have it, in the order it first came. */
export function tally(labels: string[]): { label: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const label of labels) counts.set(label, (counts.get(label) ?? 0) + 1);
  return [...counts].map(([label, count]) => ({ label, count }));
}

/** How long a call took, as people read it in the interface language: milliseconds below a second, then seconds. */
export function durationText(milliseconds: number): string {
  const format = (value: number, unit: string, digits: number) =>
    new Intl.NumberFormat(i18n.language, { style: "unit", unit, unitDisplay: "narrow", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
  return milliseconds < 1000 ? format(milliseconds, "millisecond", 0) : format(milliseconds / 1000, "second", 1);
}
