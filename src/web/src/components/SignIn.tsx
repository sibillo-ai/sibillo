import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type User } from "../api/client";
import { hasKeyboard } from "../focus";
import { getPasskey } from "../passkeys";
import { ME } from "../session";
import { Sprite } from "./Sprite";

const INPUT = "h-[42px] w-full rounded-[10px] border border-line-strong bg-surface px-3 text-base outline-none focus:border-accent";

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

  if (step !== null) {
    return (
      <Frame title={t("signIn.passkeyTitle")} subtitle={t("signIn.passkeySubtitle")}>
        <div className="flex w-full flex-col gap-3.5" aria-describedby={error ? "sign-in-error" : undefined}>
          {error && (
            <p id="sign-in-error" role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          <button type="button" disabled={busy} onClick={() => void usePasskey(step)} className="h-[42px] w-full rounded-[10px] bg-fg font-semibold text-bg disabled:opacity-60">
            {busy ? t("signIn.waitingForPasskey") : t("signIn.usePasskey")}
          </button>
          <button type="button" disabled={busy} onClick={() => (setStep(null), setError(null))} className="h-[42px] w-full rounded-[10px] border border-line-strong font-semibold disabled:opacity-60">
            {t("signIn.back")}
          </button>
        </div>
      </Frame>
    );
  }

  return (
    <Frame title={t("signIn.title")} subtitle={t("signIn.subtitle")}>
        <form onSubmit={submit} className="flex w-full flex-col gap-3.5" aria-describedby={error ? "sign-in-error" : undefined}>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13.5px] font-semibold">{t("signIn.username")}</span>
            <input name="username" autoComplete="username" required autoCapitalize="none" autoFocus={hasKeyboard()} defaultValue={username} className={INPUT} />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13.5px] font-semibold">{t("signIn.password")}</span>
            <input name="password" type="password" autoComplete="current-password" required className={INPUT} />
          </label>
          {error && (
            <p id="sign-in-error" role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          <button type="submit" disabled={busy} className="h-[42px] w-full rounded-[10px] bg-fg font-semibold text-bg disabled:opacity-60">
            {busy ? t("signIn.submitting") : t("signIn.submit")}
          </button>
        </form>
    </Frame>
  );
}

export function Frame({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <main className="flex min-h-full overflow-y-auto bg-bg px-4 py-6 text-fg">
      <div className="m-auto flex w-full max-w-[360px] flex-col items-center gap-1">
        <Sprite pose="waiting" className="h-[106px] w-[92px]" />
        <h1 className="mt-1.5 text-center text-2xl font-bold tracking-tight">{title}</h1>
        <p className="mb-[18px] text-center text-muted">{subtitle}</p>
        {children}
      </div>
    </main>
  );
}
