// Costs, from the cost ledger (MOD-007, UX-008, ADR-0073).
import { useQuery } from "@tanstack/react-query";

import { api, unwrap, type Money } from "./api/client";
import i18n from "./i18n";

export const USAGE = ["usage"] as const;

export function useUsage() {
  return useQuery({ queryKey: USAGE, queryFn: async () => unwrap(await api.GET("/me/usage")) });
}

/** Amounts per currency, shortly, in the interface language: `$0.00042`, `$1.25`, or `€2.00 · $1.00` (I18N-006). */
export function formatMoney(amounts: Money[] | null | undefined): string {
  const shown = (amounts ?? []).filter((item) => Number(item.amount) !== 0);
  if (shown.length === 0) return new Intl.NumberFormat(i18n.language, { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(0);
  return shown
    .map((item) => {
      const value = Number(item.amount);
      const options: Intl.NumberFormatOptions =
        value >= 0.01 ? { minimumFractionDigits: 2, maximumFractionDigits: 2 } : { maximumSignificantDigits: 2 };
      try {
        return new Intl.NumberFormat(i18n.language, { style: "currency", currency: item.currency, ...options }).format(value);
      } catch {
        // A currency the platform does not know: the number, then its code.
        return `${new Intl.NumberFormat(i18n.language, options).format(value)} ${item.currency}`;
      }
    })
    .join(" · ");
}

/** Whether anything was paid: local models cost nothing and show no cost. */
export function isPaid(amounts: Money[] | null | undefined): boolean {
  return (amounts ?? []).some((item) => Number(item.amount) !== 0);
}
