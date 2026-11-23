// The models of the household and the model of a conversation (MOD-010 to MOD-012, MOD-014, UX-015).
import { useQuery } from "@tanstack/react-query";

import { api, unwrap, type EgressPolicy, type ModelChoice, type ModelOption } from "./api/client";
import i18n from "./i18n";

export const MODELS = ["models"] as const;

export function useModels() {
  return useQuery({ queryKey: MODELS, queryFn: async () => unwrap(await api.GET("/models")) });
}

export function sameModel(option: ModelOption, choice: ModelChoice | null | undefined): boolean {
  return choice != null && option.connection_id === choice.connection_id && option.model === choice.model;
}

export function findModel(options: ModelOption[] | undefined, choice: ModelChoice | null | undefined): ModelOption | undefined {
  return options?.find((option) => sameModel(option, choice));
}

/**
 * Whether a data egress policy refuses a model: only local models, and one that runs remotely
 * (MOD-003, MOD-010, ADR-0091).
 */
export function refusedBy(policy: EgressPolicy | undefined, option: Pick<ModelOption, "location"> | undefined): boolean {
  return policy === "local_only" && option?.location === "remote";
}

/** A price per million tokens, as short as it can be, in the interface language: `0.27`, `2.5`, `15` (I18N-006). */
export function shortPrice(value: string): string {
  const number = Number(value);
  const options: Intl.NumberFormatOptions = number >= 1 ? { maximumFractionDigits: 2 } : { maximumSignificantDigits: 2 };
  return new Intl.NumberFormat(i18n.language, options).format(number);
}
