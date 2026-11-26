// A user's budget and usage as the app shows them: which limits to warn about, their share in words, and the
// days of a chart (UX-045, MOD-004, MOD-021, ADR-0145).
import { describe, expect, it } from "vitest";

import type { Schemas } from "../../../src/web/src/api/client";
import i18n from "../../../src/web/src/i18n";
import { lastDays, limitsToWarn, limitText, percent } from "../../../src/web/src/usage";

type LimitState = Schemas["LimitState"];

const t = i18n.getFixedT("en");

function limit(kind: "cost" | "tokens", period: "day" | "week" | "month", share: number): LimitState {
  return {
    kind,
    period,
    time_zone: "UTC",
    limit: "10",
    used: String(share * 10),
    currency: kind === "cost" ? "USD" : null,
    share,
    exhausted: share >= 1,
    starts_at: "2099-03-02T00:00:00Z",
    ends_at: "2099-03-09T00:00:00Z",
  };
}

describe("limitsToWarn", () => {
  it("warns from 80% used, the most used first", () => {
    const limits = [limit("cost", "week", 0.79), limit("tokens", "day", 0.8), limit("cost", "month", 1.02)];
    expect(limitsToWarn(limits).map((item) => item.share)).toEqual([1.02, 0.8]);
  });

  it("warns about nothing without limits", () => {
    expect(limitsToWarn([])).toEqual([]);
  });
});

describe("percent", () => {
  it("rounds down, so that a limit shows 100% only once it is reached", () => {
    expect(percent(0.899)).toBe(89);
    expect(percent(0.9999)).toBe(99);
    expect(percent(1)).toBe(100);
    expect(percent(1.05)).toBe(105);
    expect(percent(0)).toBe(0);
  });
});

describe("limitText", () => {
  it("says the share of the limit of the current period", () => {
    expect(limitText(t, limit("tokens", "day", 0.9))).toBe("90% of today's token limit");
    expect(limitText(t, limit("cost", "week", 0.5))).toBe("50% of this week's cost limit");
    expect(limitText(t, limit("cost", "month", 1))).toBe("100% of this month's cost limit");
  });
});

describe("lastDays", () => {
  const zero = { cost: [], local_tokens: 0, remote_tokens: 0, requests: 0, unpriced_requests: 0 };

  it("gives every one of the last days, oldest first, with nothing on the days without usage", () => {
    const used = { ...zero, day: "2099-03-09", requests: 4, local_tokens: 40 };
    const days = lastDays([used], "2099-03-10", 3);
    expect(days.map((day) => day.day)).toEqual(["2099-03-08", "2099-03-09", "2099-03-10"]);
    expect(days.map((day) => day.requests)).toEqual([0, 4, 0]);
  });

  it("crosses months and leap days", () => {
    expect(lastDays([], "2096-03-01", 3).map((day) => day.day)).toEqual(["2096-02-28", "2096-02-29", "2096-03-01"]);
  });
});
