// A task's schedule said in words (UX-031, TSK-003): the common forms of a cron expression, and the expression itself
// for any other.
import type { TFunction } from "i18next";

const DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"] as const;

function day(t: TFunction, value: string): string | null {
  const index = Number(value) % 7;
  if (!/^[0-7]$/.test(value)) return null;
  return t(`taskSettings.days.${DAYS[index]}`);
}

function time(minute: string, hour: string): string | null {
  if (!/^\d{1,2}$/.test(minute) || !/^\d{1,2}$/.test(hour)) return null;
  return `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
}

/** The schedule in words, such as "At 07:00, Monday to Friday", or `null` when it is not one of the common forms. */
export function describeSchedule(t: TFunction, expression: string): string | null {
  const fields = expression.trim().split(/\s+/);
  if (fields.length !== 5) return null;
  const [minute = "", hour = "", dayOfMonth = "", month = "", dayOfWeek = ""] = fields;
  if (month !== "*") return null;
  const every = /^\*\/(\d+)$/.exec(minute);
  if (every && hour === "*" && dayOfMonth === "*" && dayOfWeek === "*") return t("taskSettings.everyMinutes", { count: Number(every[1]) });
  if (/^\d{1,2}$/.test(minute) && hour === "*" && dayOfMonth === "*" && dayOfWeek === "*") return t("taskSettings.everyHour", { minute: Number(minute) });
  const at = time(minute, hour);
  if (at === null) return null;
  if (dayOfMonth === "*" && dayOfWeek === "*") return t("taskSettings.everyDay", { time: at });
  if (dayOfMonth === "*" && dayOfWeek === "1-5") return t("taskSettings.weekdays", { time: at });
  if (dayOfMonth === "*" && (dayOfWeek === "0,6" || dayOfWeek === "6,0")) return t("taskSettings.weekends", { time: at });
  if (dayOfMonth === "*") {
    const names = dayOfWeek.split(",").map((value) => day(t, value));
    if (names.some((name) => name === null)) return null;
    return t("taskSettings.onDays", { time: at, days: names.join(", ") });
  }
  if (/^\d{1,2}$/.test(dayOfMonth) && dayOfWeek === "*") return t("taskSettings.monthly", { time: at, day: Number(dayOfMonth) });
  return null;
}
