// Changing one's password, and choosing one in place of an initial password (AUTH-011, AUTH-012, ADR-0105).
import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { hasKeyboard } from "../focus";
import { useNotify } from "../notices";
import { useBusy } from "../busy";
import { ME, useSignOut } from "../session";
import { Button, FormField, Group, Notice, Page, TextInput } from "../ui";
import { Frame } from "./SignIn";

const MINIMUM_LENGTH = 12;

/** What went wrong, and the field it is about: none when it is not about what was typed. */
interface Problem {
  field: "current" | "next" | "again" | null;
  text: string;
}

/** What a refused change means for the person typing. */
function failure(t: (key: string) => string, status: number): Problem {
  if (status === 403) return { field: "current", text: t("password.wrongCurrent") };
  if (status === 429) return { field: null, text: t("signIn.rateLimited") };
  if (status === 422) return { field: "next", text: t("password.invalid") };
  return { field: null, text: t("errors.internal_error") };
}

interface FormProps {
  /** The form is alone on its screen: its button takes its width. */
  block?: boolean;
  autoFocus?: boolean;
  onChanged: () => Promise<void> | void;
}

/** The current password, then the new one twice; the second catches a typo before anything is sent. */
function PasswordForm({ block = false, autoFocus = false, onChanged }: FormProps) {
  const { t } = useTranslation();
  const [error, setError] = useState<Problem | null>(null);
  const [busy, setBusy] = useState(false);
  const about = (field: Problem["field"]) => (error?.field === field ? error.text : undefined);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const target = event.currentTarget;
    const form = new FormData(target);
    const current = String(form.get("current") ?? "");
    const next = String(form.get("next") ?? "");
    if (next !== String(form.get("again") ?? "")) {
      setError({ field: "again", text: t("password.mismatch") });
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
    <form onSubmit={(event) => void submit(event)} className="flex w-full max-w-sm flex-col gap-4">
      <FormField label={t("password.current")} error={about("current")}>
        {(ties) => <TextInput {...ties} name="current" type="password" autoComplete="current-password" required autoFocus={autoFocus && hasKeyboard()} />}
      </FormField>
      <FormField label={t("password.new")} hint={t("password.newHint", { minimum: MINIMUM_LENGTH })} error={about("next")}>
        {(ties) => <TextInput {...ties} name="next" type="password" autoComplete="new-password" required minLength={MINIMUM_LENGTH} maxLength={1024} />}
      </FormField>
      <FormField label={t("password.again")} error={about("again")}>
        {(ties) => <TextInput {...ties} name="again" type="password" autoComplete="new-password" required maxLength={1024} />}
      </FormField>
      {error?.field === null && <Notice tone="error">{error.text}</Notice>}
      <div className="flex">
        <Button type="submit" variant="primary" block={block} busy={busy}>
          {busy ? t("password.changing") : t("password.change")}
        </Button>
      </div>
    </form>
  );
}

/** Shown instead of the app until the user replaces the password an admin chose for them (AUTH-012). */
export function ChoosePassword() {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const signOut = useSignOut();
  const { busy, run } = useBusy();
  return (
    <Frame title={t("password.chooseTitle")} subtitle={t("password.chooseSubtitle")}>
      <PasswordForm block autoFocus onChanged={() => queries.invalidateQueries({ queryKey: ME })} />
      <div className="mt-3 flex w-full">
        <Button block busy={busy("signOut")} onClick={() => void run("signOut", signOut)}>
          {t("shell.signOut")}
        </Button>
      </div>
    </Frame>
  );
}

/**
 * The user's password, changed with the current one; their other devices are signed out (AUTH-011).
 * It opens the Security settings, so it is their page; the password is a region of it.
 */
export function PasswordSection() {
  const { t } = useTranslation();
  const notify = useNotify();
  return (
    <Page title={t("settings.security")}>
      <Group role="region" title={t("password.title")} description={t("password.hint")}>
        <PasswordForm onChanged={() => notify({ kind: "info", title: t("password.changed") })} />
      </Group>
    </Page>
  );
}
