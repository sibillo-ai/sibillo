// A task's schedule said in words (UX-031, TSK-003, ADR-0109): its start and its iCalendar recurrence, for the
// forms people use; any other recurrence is shown as written.
import type { TFunction } from "i18next";

const DAYS: Record<string, string> = { MO: "monday", TU: "tuesday", WE: "wednesday", TH: "thursday", FR: "friday", SA: "saturday", SU: "sunday" };
const ORDINALS: Record<string, string> = { "1": "first", "2": "second", "3": "third", "4": "fourth", "-1": "last" };
const WEEKDAYS = ["MO", "TU", "WE", "TH", "FR"];

function parts(rule: string): Map<string, string> | null {
  const found = new Map<string, string>();
  for (const item of rule.split(";")) {
    const [key, value] = item.split("=");
    if (!key || value === undefined) return null;
    found.set(key.toUpperCase(), value.toUpperCase());
  }
  return found;
}

/** An RFC 5545 date, `YYYYMMDD` or `YYYYMMDDTHHMMSS[Z]`, as a date. */
function untilDate(value: string): Date | null {
  const match = /^(\d{4})(\d{2})(\d{2})(T(\d{2})(\d{2})(\d{2})(Z?))?$/.exec(value);
  if (!match) return null;
  const [, y, m, d, , hh = "00", mm = "00", ss = "00", z] = match;
  return z ? new Date(Date.UTC(+y!, +m! - 1, +d!, +hh, +mm, +ss)) : new Date(+y!, +m! - 1, +d!, +hh, +mm, +ss);
}

function dayNames(t: TFunction, values: string[]): string | null {
  const names = values.map((value) => (DAYS[value] ? t(`taskSettings.days.${DAYS[value]}`) : null));
  if (names.some((name) => name === null)) return null;
  return names.join(", ");
}

/** The schedule in words, such as "At 07:00, Monday to Friday", or `null` when it is not one of the common forms. */
export function describeSchedule(t: TFunction, language: string, start: string, recurrence: string[]): string | null {
  const when = new Date(start);
  if (Number.isNaN(when.getTime())) return null;
  const time = start.slice(11, 16);
  const date = (value: Date) => new Intl.DateTimeFormat(language, { dateStyle: "medium" }).format(value);
  const lines = recurrence.map((line) => line.trim()).filter((line) => line !== "");
  if (lines.length === 0) return t("taskSettings.once", { date: date(when), time });
  const rules = lines.filter((line) => line.toUpperCase().startsWith("RRULE:"));
  if (rules.length !== 1) return null;
  const rule = parts(rules[0]!.slice(6));
  if (rule === null) return null;
  const interval = Number(rule.get("INTERVAL") ?? "1");
  if (!Number.isInteger(interval) || interval < 1) return null;
  const byDay = rule.get("BYDAY")?.split(",") ?? [];
  let pattern: string | null = null;
  let timed = true;
  switch (rule.get("FREQ")) {
    case "MINUTELY":
      pattern = t("taskSettings.everyMinutes", { count: interval });
      timed = false;
      break;
    case "HOURLY":
      pattern = interval === 1 ? t("taskSettings.everyHour") : t("taskSettings.everyHours", { count: interval });
      timed = false;
      break;
    case "DAILY":
      pattern = interval === 1 ? t("taskSettings.everyDay") : t("taskSettings.everyDays", { count: interval });
      break;
    case "WEEKLY": {
      if (interval === 1 && byDay.length === 5 && WEEKDAYS.every((day) => byDay.includes(day))) {
        pattern = t("taskSettings.weekdays");
        break;
      }
      const days = byDay.length ? dayNames(t, byDay) : null;
      if (byDay.length && days === null) return null;
      const every = interval === 1 ? t("taskSettings.everyWeek") : t("taskSettings.everyWeeks", { count: interval });
      pattern = days ? t("taskSettings.onDays", { every, days }) : every;
      break;
    }
    case "MONTHLY": {
      const every = interval === 1 ? t("taskSettings.everyMonth") : t("taskSettings.everyMonths", { count: interval });
      const nth = byDay.length === 1 ? /^(-?\d)([A-Z]{2})$/.exec(byDay[0]!) : null;
      const monthDay = rule.get("BYMONTHDAY");
      if (nth && ORDINALS[nth[1]!] && DAYS[nth[2]!]) {
        pattern = t("taskSettings.nthWeekday", { nth: t(`taskSettings.ordinals.${ORDINALS[nth[1]!]}`), day: t(`taskSettings.days.${DAYS[nth[2]!]}`), every });
      } else if (monthDay && /^\d{1,2}$/.test(monthDay) && byDay.length === 0) {
        pattern = t("taskSettings.monthDay", { day: Number(monthDay), every });
      } else if (!monthDay && byDay.length === 0) {
        pattern = every;
      } else return null;
      break;
    }
    case "YEARLY":
      pattern = interval === 1 ? t("taskSettings.everyYear") : t("taskSettings.everyYears", { count: interval });
      break;
    default:
      return null;
  }
  let words = timed ? t("taskSettings.atTime", { time, pattern }) : pattern;
  const count = rule.get("COUNT");
  if (count !== undefined) words += count === "1" ? t("taskSettings.timesOnce") : t("taskSettings.times", { count: Number(count) });
  const until = rule.get("UNTIL");
  if (until !== undefined) {
    const end = untilDate(until);
    if (end === null) return null;
    words += t("taskSettings.until", { date: date(end) });
  }
  if (lines.length > 1) words += t("taskSettings.otherDates");
  return words;
}
