// Changing one's password, and choosing one in place of an initial password (AUTH-011, AUTH-012, ADR-0105).
import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { hasKeyboard } from "../focus";
import { useNotify } from "../notices";
import { ME, useSignOut } from "../session";
import { Frame } from "./SignIn";

const MINIMUM_LENGTH = 12;

/** What a refused change means for the person typing. */
function failure(t: (key: string) => string, status: number): string {
  if (status === 403) return t("password.wrongCurrent");
  if (status === 429) return t("signIn.rateLimited");
  if (status === 422) return t("password.invalid");
  return t("errors.internal_error");
}

interface FormProps {
  /** The class of the inputs, which follows the surface the form is on. */
  input: string;
  /** The class of the submit button. */
  button: string;
  autoFocus?: boolean;
  onChanged: () => Promise<void> | void;
}

/** The current password, then the new one twice; the second catches a typo before anything is sent. */
function PasswordForm({ input, button, autoFocus = false, onChanged }: FormProps) {
  const { t } = useTranslation();
  const ids = { current: useId(), next: useId(), again: useId(), error: useId() };
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const target = event.currentTarget;
    const form = new FormData(target);
    const current = String(form.get("current") ?? "");
    const next = String(form.get("next") ?? "");
    if (next !== String(form.get("again") ?? "")) {
      setError(t("password.mismatch"));
      return;
    }
    setBusy(true);
    setError(null);
    const result = await api.POST("/me/password", { body: { current_password: current, new_password: next } });
    setBusy(false);
    if (!result.response.ok) {
      setError(failure(t, result.response.status));
      return;
    }
    target.reset();
    await onChanged();
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="flex w-full max-w-[360px] flex-col gap-3.5" aria-describedby={error ? ids.error : undefined}>
      <label htmlFor={ids.current} className="flex flex-col gap-1.5">
        <span className="text-[13.5px] font-semibold">{t("password.current")}</span>
        <input id={ids.current} name="current" type="password" autoComplete="current-password" required autoFocus={autoFocus && hasKeyboard()} className={input} />
      </label>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={ids.next} className="flex flex-col gap-1.5">
          <span className="text-[13.5px] font-semibold">{t("password.new")}</span>
          <input id={ids.next} name="next" type="password" autoComplete="new-password" required minLength={MINIMUM_LENGTH} maxLength={1024} aria-describedby={`${ids.next}-hint`} className={input} />
        </label>
        <span id={`${ids.next}-hint`} className="text-[13px] text-muted">
          {t("password.newHint", { minimum: MINIMUM_LENGTH })}
        </span>
      </div>
      <label htmlFor={ids.again} className="flex flex-col gap-1.5">
        <span className="text-[13.5px] font-semibold">{t("password.again")}</span>
        <input id={ids.again} name="again" type="password" autoComplete="new-password" required maxLength={1024} className={input} />
      </label>
      {error && (
        <p id={ids.error} role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <button type="submit" disabled={busy} className={button}>
        {busy ? t("password.changing") : t("password.change")}
      </button>
    </form>
  );
}

/** Shown instead of the app until the user replaces the password an admin chose for them (AUTH-012). */
export function ChoosePassword() {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const signOut = useSignOut();
  return (
    <Frame title={t("password.chooseTitle")} subtitle={t("password.chooseSubtitle")}>
      <PasswordForm
        autoFocus
        input="h-[42px] w-full rounded-[10px] border border-line-strong bg-surface px-3 text-base outline-none focus:border-accent"
        button="h-[42px] w-full rounded-[10px] bg-fg font-semibold text-bg disabled:opacity-60"
        onChanged={() => queries.invalidateQueries({ queryKey: ME })}
      />
      <button type="button" onClick={() => void signOut()} className="mt-3.5 h-[42px] w-full max-w-[360px] rounded-[10px] border border-line-strong font-semibold">
        {t("shell.signOut")}
      </button>
    </Frame>
  );
}

/** The user's password, changed with the current one; their other devices are signed out (AUTH-011). */
export function PasswordSection() {
  const { t } = useTranslation();
  const heading = useId();
  const notify = useNotify();
  return (
    <section aria-labelledby={heading} className="flex flex-col gap-3">
      <div>
        <h2 id={heading} className="mb-1 text-base font-bold">
          {t("password.title")}
        </h2>
        <p className="max-w-[62ch] text-sm text-muted">{t("password.hint")}</p>
      </div>
      <PasswordForm
        input="h-10 w-full rounded-[10px] border border-line-strong bg-bg px-3 outline-none focus:border-accent"
        button="inline-flex h-[38px] items-center justify-center gap-2 self-start rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg disabled:opacity-50"
        onChanged={() => notify({ kind: "info", title: t("password.changed") })}
      />
    </section>
  );
}
