// A user's budget and usage over time, as the app shows them (UX-045, MOD-004, MOD-021, ADR-0145).
import { useQuery } from "@tanstack/react-query";
import type { TFunction } from "i18next";

import { api, unwrap, type Schemas } from "./api/client";
import { USAGE } from "./costs";
import i18n from "./i18n";

type LimitState = Schemas["LimitState"];
type UsageDay = Schemas["UsageDay"];

/** From this share of a limit used, the user is warned where they write. */
export const WARN_SHARE = 0.8;
/** The days of usage the overview gives one by one. */
export const DAYS = 30;

/** The time zone of this device, which the days and months of usage are counted in. */
export function deviceTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

/** The user's own usage, refreshed with the costs after each run (`USAGE`). */
export function useOwnUsage() {
  const zone = deviceTimeZone();
  return useQuery({
    queryKey: [...USAGE, "overview", zone],
    queryFn: async () => unwrap(await api.GET("/me/usage/overview", { params: { query: { time_zone: zone } } })),
  });
}

/** A member's usage, for a tenant admin. */
export function useMemberUsage(userId: string) {
  const zone = deviceTimeZone();
  return useQuery({
    queryKey: [...USAGE, "member", userId, zone],
    queryFn: async () =>
      unwrap(await api.GET("/tenant/users/{user_id}/usage", { params: { path: { user_id: userId }, query: { time_zone: zone } } })),
  });
}

/** The limits used at least `WARN_SHARE`, the most used first. */
export function limitsToWarn(limits: LimitState[]): LimitState[] {
  return limits.filter((limit) => limit.share >= WARN_SHARE).sort((a, b) => b.share - a.share);
}

/** A share as a whole percent, rounded down, so that 100% means the limit is reached. */
export function percent(share: number): number {
  return Math.floor(Math.round(share * 1e6) / 1e4);
}

/** "90% of today's token limit": the share of the limit of its current period. */
export function limitText(t: TFunction, limit: LimitState): string {
  return t(`budget.share.${limit.kind}.${limit.period}`, { percent: percent(limit.share) });
}

/** When a limit's period ends, in the interface language, on this device's clock. */
export function untilText(language: string, limit: LimitState): string {
  return new Intl.DateTimeFormat(language, { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }).format(new Date(limit.ends_at));
}

/** Today's date in a time zone, as `YYYY-MM-DD`. */
export function todayIn(zone: string, now = new Date()): string {
  const parts = new Intl.DateTimeFormat(i18n.language, { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit", numberingSystem: "latn" }).formatToParts(now);
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function shifted(day: string, by: number): string {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1, (date ?? 1) + by)).toISOString().slice(0, 10);
}

/** Each of the `count` days up to `today`, oldest first, with nothing on the days without usage. */
export function lastDays(days: UsageDay[], today: string, count = DAYS): UsageDay[] {
  const byDay = new Map(days.map((day) => [day.day, day]));
  return Array.from({ length: count }, (_, index) => {
    const day = shifted(today, index - count + 1);
    return byDay.get(day) ?? { day, cost: [], local_tokens: 0, remote_tokens: 0, requests: 0, unpriced_requests: 0 };
  });
}
