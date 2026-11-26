// A user's usage over time and the state of their budget: for themself among their settings and where they write,
// and for the household's admins on a member's page (UX-045, MOD-004, MOD-021, ADR-0145).
import { TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Money, Schemas } from "../api/client";
import { formatMoney } from "../costs";
import { Card, Group, Loading, Notice, Page, Row } from "../ui";
import { deviceTimeZone, lastDays, limitsToWarn, limitText, todayIn, untilText, useOwnUsage } from "../usage";

type UsageOverview = Schemas["UsageOverview"];
type UsageTotals = Schemas["UsageTotals"];
type LimitState = Schemas["LimitState"];

/** The user's own usage, among their settings. */
export function UsageSection() {
  const { t } = useTranslation();
  const usage = useOwnUsage();
  return (
    <Page title={t("usage.page")} description={t("usage.hint")}>
      <Group title={t("usage.title")} role="group">
        {usage.data ? <UsageView overview={usage.data} /> : <Card>{usage.isError ? <p className="p-4 text-small text-ink-2">{t("errors.internal_error")}</p> : <Loading />}</Card>}
      </Group>
    </Page>
  );
}

function useFormat() {
  const { t, i18n } = useTranslation();
  const number = new Intl.NumberFormat(i18n.language);
  const money = (amounts: Money[]) => formatMoney(amounts);
  const tokens = (count: number) => t("usage.tokens", { count, formatted: number.format(count) });
  return { t, language: i18n.language, number, money, tokens };
}

/** A part of a limit, as an amount of its currency or a number of tokens. */
function amountOf(limit: LimitState, value: string, tokens: (count: number) => string): string {
  return limit.kind === "cost" ? formatMoney([{ amount: value, currency: limit.currency ?? "USD" }]) : tokens(Number(value));
}

/** The limits of the budget, the totals since the account was created, the last days, the months and the models. */
export function UsageView({ overview }: { overview: UsageOverview }) {
  const { t, language, number, money, tokens } = useFormat();
  const since = new Intl.DateTimeFormat(language, { dateStyle: "long" }).format(new Date(overview.since));
  const days = lastDays(overview.days, todayIn(overview.time_zone));
  const busiest = Math.max(1, ...days.map((day) => day.local_tokens + day.remote_tokens));
  const totals = (sums: UsageTotals) =>
    [sums.cost.some((item) => Number(item.amount) !== 0) ? money(sums.cost) : null, sums.local_tokens ? t("usage.local", { tokens: tokens(sums.local_tokens) }) : null, sums.remote_tokens ? t("usage.remote", { tokens: tokens(sums.remote_tokens) }) : null]
      .filter(Boolean)
      .join(" · ") || t("usage.nothing");
  return (
    <div className="flex flex-col gap-4">
      <Card rows>
        {overview.limits.length === 0 && <Row title={t("usage.noBudget")} />}
        {overview.limits.map((limit) => (
          <Row
            key={limit.kind}
            title={limitText(t, limit)}
            description={`${t("usage.usedOf", { used: amountOf(limit, limit.used, tokens), limit: amountOf(limit, limit.limit, tokens) })} · ${t("budget.until", { until: untilText(language, limit) })}`}
          >
            <meter className="h-2 w-28 flex-none" min={0} max={1} low={0.8} high={0.99} optimum={0} value={Math.min(limit.share, 1)} aria-label={limitText(t, limit)} />
          </Row>
        ))}
      </Card>
      <Card rows>
        <Row title={t("usage.since", { date: since })} description={totals(overview.total)}>
          <span className="text-small text-ink-2 tabular-nums">{t("usage.requests", { count: overview.total.requests, formatted: number.format(overview.total.requests) })}</span>
        </Row>
        {overview.total.unpriced_requests > 0 && <Row title={t("usage.unpriced", { count: overview.total.unpriced_requests, formatted: number.format(overview.total.unpriced_requests) })} />}
      </Card>
      <figure className="flex flex-col gap-2">
        <figcaption className="text-small font-semibold">{t("usage.lastDays")}</figcaption>
        <ol aria-label={t("usage.lastDays")} className="flex h-24 items-end gap-px rounded-md border border-line bg-surface p-2">
          {days.map((day) => {
            const used = day.local_tokens + day.remote_tokens;
            const label = `${new Intl.DateTimeFormat(language, { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${day.day}T00:00:00Z`))}: ${totals(day)}`;
            return (
              <li key={day.day} title={label} className="flex h-full min-w-0 flex-1 items-end">
                <span className="sr-only">{label}</span>
                <span aria-hidden="true" className="w-full rounded-t-sm bg-accent" style={{ height: `${used === 0 ? 0 : Math.max(4, Math.round((used / busiest) * 100))}%` }} />
              </li>
            );
          })}
        </ol>
      </figure>
      {overview.months.length > 0 && (
        <Group title={t("usage.byMonth")}>
          <Card rows>
            {[...overview.months].reverse().map((month) => (
              <Row key={month.month} title={new Intl.DateTimeFormat(language, { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(`${month.month}-01T00:00:00Z`))} description={totals(month)} />
            ))}
          </Card>
        </Group>
      )}
      {overview.models.length > 0 && (
        <Group title={t("usage.byModel")}>
          <Card rows>
            {overview.models.map((model) => (
              <Row key={`${model.provider} ${model.model}`} title={<span className="break-all font-mono text-small">{model.model}</span>} description={`${model.provider} · ${totals(model)}`} />
            ))}
          </Card>
        </Group>
      )}
      <p className="text-caption text-ink-3">{t("usage.zone", { zone: overview.time_zone || deviceTimeZone() })}</p>
    </div>
  );
}

/** Where the user writes: a word once a limit's current period is 80% used, and when it starts again. */
export function BudgetWarning() {
  const { t, i18n } = useTranslation();
  const usage = useOwnUsage();
  const [limit] = limitsToWarn(usage.data?.limits ?? []);
  if (!limit) return null;
  const words = { share: limitText(t, limit), until: untilText(i18n.language, limit) };
  return (
    <Notice tone="warn" role="status" icon={<TriangleAlert aria-hidden="true" />}>
      {limit.exhausted ? t("budget.exhausted", words) : t("budget.warning", words)}
    </Notice>
  );
}

/** Until when a used-up budget refuses the user's requests, for a run refused with `budget.exhausted`. */
export function BudgetUntil() {
  const { t, i18n } = useTranslation();
  const usage = useOwnUsage();
  const limit = usage.data?.limits.find((item) => item.exhausted);
  if (!limit) return null;
  return <> {t("budget.until", { until: untilText(i18n.language, limit) })}</>;
}
