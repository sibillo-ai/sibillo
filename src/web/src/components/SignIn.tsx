import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type User } from "../api/client";
import { hasKeyboard } from "../focus";
import { getPasskey } from "../passkeys";
import { ME } from "../session";
import { Button, FormField, Notice, TextInput } from "../ui";
import { Sprite } from "./Sprite";

const DEVICE_NAME = () => navigator.userAgent.slice(0, 100) || "browser";

/** A sign-in waiting for a passkey, after the password (AUTH-010, ADR-0094). */
interface PasskeyStep {
  token: string;
  options: Record<string, unknown>;
}

/**
 * Sign in with a cookie session: the token never reaches the page's scripts (AUTH-005). A user
 * who has passkeys is then asked for one, and can ask again or go back to the password (UX-026).
 */
export function SignIn() {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState<PasskeyStep | null>(null);
  const [username, setUsername] = useState("");

  function signedIn(user: User) {
    queries.setQueryData(ME, user);
  }

  function failure(status: number) {
    return t(status === 401 ? "signIn.invalid" : status === 429 ? "signIn.rateLimited" : status === 503 ? "signIn.passkeysUnavailable" : "signIn.failed");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    setUsername(String(form.get("username") ?? ""));
    const result = await api.POST("/auth/login", {
      body: {
        username: String(form.get("username") ?? ""),
        password: String(form.get("password") ?? ""),
        device_name: DEVICE_NAME(),
        session_delivery: "cookie",
      },
    });
    setBusy(false);
    if (result.data !== undefined) {
      if ("sign_in_token" in result.data) setStep({ token: result.data.sign_in_token, options: result.data.options });
      else signedIn(result.data.user);
      return;
    }
    setError(failure(result.response.status));
  }

  async function usePasskey(current: PasskeyStep) {
    setBusy(true);
    setError(null);
    let credential: Record<string, unknown>;
    try {
      credential = await getPasskey(current.options);
    } catch {
      // Cancelled, timed out, or no passkey of this user on the device: the token is still good.
      setBusy(false);
      setError(t("signIn.passkeyNotUsed"));
      return;
    }
    const result = await api.POST("/auth/login/passkey", {
      body: { sign_in_token: current.token, credential, device_name: DEVICE_NAME(), session_delivery: "cookie" },
    });
    setBusy(false);
    if (result.data !== undefined) {
      signedIn(result.data.user);
      return;
    }
    // The token is used once: anything but a session means the password again.
    setStep(null);
    setError(result.response.status === 401 ? t("signIn.passkeyRefused") : failure(result.response.status));
  }

  // The error is announced when it appears, and described by the form it is about.
  const problem = error && (
    <div id="sign-in-error">
      <Notice tone="error">{error}</Notice>
    </div>
  );

  if (step !== null) {
    return (
      <Frame title={t("signIn.passkeyTitle")} subtitle={t("signIn.passkeySubtitle")}>
        <div className="flex w-full flex-col gap-4" aria-describedby={error ? "sign-in-error" : undefined}>
          {problem}
          <Button variant="primary" block busy={busy} onClick={() => void usePasskey(step)}>
            {busy ? t("signIn.waitingForPasskey") : t("signIn.usePasskey")}
          </Button>
          <Button block disabled={busy} onClick={() => (setStep(null), setError(null))}>
            {t("signIn.back")}
          </Button>
        </div>
      </Frame>
    );
  }

  return (
    <Frame title={t("signIn.title")} subtitle={t("signIn.subtitle")}>
      <form onSubmit={submit} className="flex w-full flex-col gap-4" aria-describedby={error ? "sign-in-error" : undefined}>
        <FormField label={t("signIn.username")}>
          {(ties) => <TextInput {...ties} name="username" autoComplete="username" required autoCapitalize="none" autoFocus={hasKeyboard()} defaultValue={username} />}
        </FormField>
        <FormField label={t("signIn.password")}>
          {(ties) => <TextInput {...ties} name="password" type="password" autoComplete="current-password" required />}
        </FormField>
        {problem}
        <Button type="submit" variant="primary" block busy={busy}>
          {busy ? t("signIn.submitting") : t("signIn.submit")}
        </Button>
      </form>
    </Frame>
  );
}

/** A screen that stands alone, before the app: one card on the page, with the sprite, a title and what it is for (ADR-0111). */
export function Frame({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <main className="flex min-h-full overflow-y-auto bg-sunken px-4 py-6 text-ink">
      <div className="m-auto flex w-full max-w-dialog-sm flex-col items-center gap-4 rounded-lg border border-line bg-surface p-6 shadow-float md:p-8">
        <Sprite pose="waiting" className="h-20 w-16" />
        <header className="text-center">
          <h1 className="font-serif text-display">{title}</h1>
          <p className="mt-1 text-body text-ink-2">{subtitle}</p>
        </header>
        {children}
      </div>
    </main>
  );
}
