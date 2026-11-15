// The user's passkeys, and the members of the household with theirs for its admins (UX-026, AUTH-010, ADR-0094).
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api, unwrap, type Schemas, type User } from "../api/client";
import { useNotify } from "../notices";
import { createPasskey, passkeysSupported } from "../passkeys";

type Passkey = Schemas["Passkey"];

const PASSKEYS = ["me", "passkeys"] as const;
const BUTTON = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-hover disabled:opacity-50";
const PRIMARY = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg disabled:opacity-50";
const DANGER = "h-[38px] rounded-[10px] bg-danger px-4 text-sm font-semibold text-on-danger disabled:opacity-50";
const INPUT = "h-10 w-full rounded-[10px] border border-line-strong bg-bg px-3 outline-none focus:border-accent";
const DIALOG = "rise fixed top-1/2 left-1/2 z-50 w-[min(92vw,28rem)] -translate-x-1/2 -translate-y-1/2 rounded-[20px] bg-raised p-[22px] shadow-soft";

/** What a failed request means for the person typing their password. */
function problemText(t: (key: string) => string, error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return t("passkeys.wrongPassword");
    if (error.status === 429) return t("signIn.rateLimited");
    if (error.status === 503) return t("passkeys.unavailable");
    if (error.code === "auth.passkey_rejected") return t("passkeys.rejected");
  }
  return t("errors.internal_error");
}

/** The user's passkeys: listed, added and removed with the password (UX-026). */
export function PasskeysSection() {
  const { t, i18n } = useTranslation();
  const heading = useId();
  const queries = useQueryClient();
  const passkeys = useQuery({ queryKey: PASSKEYS, queryFn: async () => unwrap(await api.GET("/me/passkeys")) });
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<Passkey | null>(null);
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });
  const refresh = () => queries.invalidateQueries({ queryKey: PASSKEYS });
  const available = passkeys.data?.available ?? true;
  const items = passkeys.data?.items ?? [];
  return (
    <section aria-labelledby={heading} className="flex flex-col gap-3">
      <div>
        <h2 id={heading} className="mb-1 text-base font-bold">
          {t("passkeys.title")}
        </h2>
        <p className="max-w-[62ch] text-sm text-muted">{t("passkeys.hint")}</p>
      </div>
      {!available && (
        <p role="note" className="max-w-[62ch] rounded-xl border border-line px-3 py-2.5 text-sm">
          {t("passkeys.unavailable")}
        </p>
      )}
      {passkeys.data && items.length === 0 && <p className="text-sm text-muted">{t("passkeys.none")}</p>}
      <ul aria-label={t("passkeys.title")} className="flex flex-col gap-2">
        {items.map((passkey) => (
          <li key={passkey.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl border border-line bg-surface px-4 py-3">
            <KeyRound className="size-[18px] flex-none text-accent" aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <span className="block font-bold break-words">{passkey.name}</span>
              <span className="block text-[13px] text-muted">
                {t("passkeys.added", { date: date.format(new Date(passkey.created_at)) })}
                {" · "}
                {passkey.last_used_at === null ? t("passkeys.neverUsed") : t("passkeys.lastUsed", { date: date.format(new Date(passkey.last_used_at)) })}
              </span>
            </span>
            <button type="button" className={`${BUTTON} h-8 px-3 text-[13px]`} aria-label={t("passkeys.removeLabel", { name: passkey.name })} onClick={() => setRemoving(passkey)}>
              {t("passkeys.remove")}
            </button>
          </li>
        ))}
      </ul>
      {available && passkeysSupported() && (
        <div>
          <button type="button" className={BUTTON} onClick={() => setAdding(true)}>
            <Plus className="size-[18px]" aria-hidden="true" />
            {t("passkeys.add")}
          </button>
        </div>
      )}
      {adding && <AddPasskeyDialog onClose={() => setAdding(false)} onAdded={refresh} />}
      {removing && <RemovePasskeyDialog key={removing.id} passkey={removing} onClose={() => setRemoving(null)} onRemoved={refresh} />}
    </section>
  );
}

function PasswordField({ id }: { id: string }) {
  const { t } = useTranslation();
  return (
    <label htmlFor={id} className="flex flex-col gap-1.5">
      <span className="text-[13.5px] font-semibold">{t("signIn.password")}</span>
      <input id={id} name="password" type="password" autoComplete="current-password" required className={INPUT} />
    </label>
  );
}

function AddPasskeyDialog({ onClose, onAdded }: { onClose: () => void; onAdded: () => Promise<void> }) {
  const { t } = useTranslation();
  const notify = useNotify();
  const nameField = useId();
  const passwordField = useId();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const registration = unwrap(await api.POST("/me/passkeys/registrations", { body: { password: String(form.get("password") ?? "") } }));
      let credential: Record<string, unknown>;
      try {
        credential = await createPasskey(registration.options);
      } catch {
        setError(t("passkeys.notMade"));
        return;
      }
      unwrap(await api.POST("/me/passkeys", { body: { registration_id: registration.registration_id, name: String(form.get("name") ?? "").trim(), credential } }));
      await onAdded();
      notify({ kind: "info", title: t("passkeys.addedNotice") });
      onClose();
    } catch (failure) {
      setError(problemText(t, failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className={DIALOG}>
          <Dialog.Title className="mb-2 text-lg font-bold">{t("passkeys.add")}</Dialog.Title>
          <Dialog.Description className="text-sm text-muted">{t("passkeys.addHint")}</Dialog.Description>
          <form onSubmit={(event) => void add(event)} className="mt-3.5 flex flex-col gap-3.5">
            <label htmlFor={nameField} className="flex flex-col gap-1.5">
              <span className="text-[13.5px] font-semibold">{t("passkeys.name")}</span>
              <input id={nameField} name="name" required maxLength={100} placeholder={t("passkeys.namePlaceholder")} className={INPUT} />
            </label>
            <PasswordField id={passwordField} />
            {error && (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Dialog.Close className={BUTTON}>{t("connection.cancel")}</Dialog.Close>
              <button type="submit" disabled={busy} className={PRIMARY}>
                {t("passkeys.confirmAdd")}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function RemovePasskeyDialog({ passkey, onClose, onRemoved }: { passkey: Passkey; onClose: () => void; onRemoved: () => Promise<void> }) {
  const { t } = useTranslation();
  const passwordField = useId();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function remove(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const result = await api.POST("/me/passkeys/{passkey_id}/remove", {
        params: { path: { passkey_id: passkey.id } },
        body: { password: String(form.get("password") ?? "") },
      });
      if (!result.response.ok) unwrap(result);
      await onRemoved();
      onClose();
    } catch (failure) {
      setError(problemText(t, failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className={DIALOG}>
          <Dialog.Title className="mb-2 text-lg font-bold">{t("passkeys.removeLabel", { name: passkey.name })}</Dialog.Title>
          <Dialog.Description className="text-sm text-muted">{t("passkeys.removeHint")}</Dialog.Description>
          <form onSubmit={(event) => void remove(event)} className="mt-3.5 flex flex-col gap-3.5">
            <PasswordField id={passwordField} />
            {error && (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Dialog.Close className={BUTTON}>{t("connection.cancel")}</Dialog.Close>
              <button type="submit" disabled={busy} className={DANGER}>
                {t("passkeys.remove")}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** The household's members, with how many passkeys each has, for its admins to remove (UX-026). */
export function MembersSection() {
  const { t } = useTranslation();
  const heading = useId();
  const users = useQuery({
    queryKey: ["tenant", "users"],
    queryFn: async () => unwrap(await api.GET("/tenant/users", { params: { query: { limit: 100 } } })).items,
  });
  return (
    <section aria-labelledby={heading} className="flex flex-col gap-3">
      <div>
        <h2 id={heading} className="mb-1 text-base font-bold">
          {t("members.title")}
        </h2>
        <p className="max-w-[62ch] text-sm text-muted">{t("members.hint")}</p>
      </div>
      <ul aria-label={t("members.title")} className="flex flex-col gap-2">
        {(users.data ?? []).map((user) => (
          <Member key={user.id} user={user} />
        ))}
      </ul>
    </section>
  );
}

function Member({ user }: { user: User }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const key = ["tenant", "users", user.id, "passkeys"];
  const count = useQuery({
    queryKey: key,
    queryFn: async () => unwrap(await api.GET("/tenant/users/{user_id}/passkeys", { params: { path: { user_id: user.id } } })).count,
  });
  const [confirming, setConfirming] = useState(false);

  async function remove() {
    const result = await api.DELETE("/tenant/users/{user_id}/passkeys", { params: { path: { user_id: user.id } } });
    setConfirming(false);
    if (!result.response.ok) {
      notify({ kind: "error", title: t("errors.title"), text: t("errors.internal_error") });
      return;
    }
    await queries.invalidateQueries({ queryKey: key });
  }

  const passkeys = count.data;
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl border border-line bg-surface px-4 py-3">
      <span className="min-w-0 flex-1">
        <span className="block font-bold break-words">{user.display_name}</span>
        <span className="block text-[13px] text-muted">
          {user.username}
          {passkeys !== undefined && " · "}
          {passkeys === undefined ? "" : passkeys === 0 ? t("members.noPasskeys") : passkeys === 1 ? t("members.onePasskey") : t("members.passkeys", { count: passkeys })}
        </span>
      </span>
      {passkeys !== undefined && passkeys > 0 && (
        <button type="button" className={`${BUTTON} h-8 px-3 text-[13px]`} aria-label={t("members.removeLabel", { username: user.username })} onClick={() => setConfirming(true)}>
          {t("passkeys.remove")}
        </button>
      )}
      <Dialog.Root open={confirming} onOpenChange={setConfirming}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
          <Dialog.Content role="alertdialog" className={DIALOG}>
            <Dialog.Title className="mb-2 text-lg font-bold">{t("members.removeTitle", { name: user.display_name })}</Dialog.Title>
            <Dialog.Description className="text-muted">{t("members.removeBody", { username: user.username })}</Dialog.Description>
            <div className="mt-[18px] flex justify-end gap-2">
              <Dialog.Close className={BUTTON}>{t("connection.cancel")}</Dialog.Close>
              <button type="button" className={DANGER} onClick={() => void remove()}>
                {t("members.remove")}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </li>
  );
}
