// The user's passkeys, and the members of the household with theirs for its admins (UX-026, AUTH-010, ADR-0094).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api, unwrap, type Schemas, type User } from "../api/client";
import { useBusy } from "../busy";
import { useNotify } from "../notices";
import { createPasskey, passkeysSupported } from "../passkeys";
import { Avatar, Button, Card, Dialog, EmptyState, FormField, Group, Loading, Notice, Page, Row, TextInput, Tile } from "../ui";

type Passkey = Schemas["Passkey"];

const PASSKEYS = ["me", "passkeys"] as const;

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
  const queries = useQueryClient();
  const passkeys = useQuery({ queryKey: PASSKEYS, queryFn: async () => unwrap(await api.GET("/me/passkeys")) });
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<Passkey | null>(null);
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });
  const refresh = () => queries.invalidateQueries({ queryKey: PASSKEYS });
  const available = passkeys.data?.available ?? true;
  const items = passkeys.data?.items ?? [];
  const add = available && passkeysSupported() && (
    <Button size="sm" onClick={() => setAdding(true)}>
      <Plus aria-hidden="true" />
      {t("passkeys.add")}
    </Button>
  );
  return (
    <Group role="region" title={t("passkeys.title")} description={t("passkeys.hint")} action={items.length > 0 && add}>
      {!available && <Notice role="note">{t("passkeys.unavailable")}</Notice>}
      {passkeys.isPending && (
        <Card>
          <Loading />
        </Card>
      )}
      {passkeys.data && (
        <Card>
          {items.length === 0 ? (
            <EmptyState icon={<KeyRound />} title={t("passkeys.none")} action={add || undefined}>
              {t("passkeys.noneHint")}
            </EmptyState>
          ) : (
            <ul aria-label={t("passkeys.title")} className="divide-y divide-line">
              {items.map((passkey) => (
                <li key={passkey.id}>
                  <Row
                    leading={
                      <Tile>
                        <KeyRound />
                      </Tile>
                    }
                    title={<span className="min-w-0 break-words">{passkey.name}</span>}
                    description={
                      <>
                        {t("passkeys.added", { date: date.format(new Date(passkey.created_at)) })}
                        {" · "}
                        {passkey.last_used_at === null ? t("passkeys.neverUsed") : t("passkeys.lastUsed", { date: date.format(new Date(passkey.last_used_at)) })}
                      </>
                    }
                  >
                    <Button variant="danger" size="sm" aria-label={t("passkeys.removeLabel", { name: passkey.name })} onClick={() => setRemoving(passkey)}>
                      {t("passkeys.remove")}
                    </Button>
                  </Row>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
      {adding && <AddPasskeyDialog onClose={() => setAdding(false)} onAdded={refresh} />}
      {removing && <RemovePasskeyDialog key={removing.id} passkey={removing} onClose={() => setRemoving(null)} onRemoved={refresh} />}
    </Group>
  );
}

function PasswordField() {
  const { t } = useTranslation();
  return <FormField label={t("signIn.password")}>{(ties) => <TextInput {...ties} name="password" type="password" autoComplete="current-password" required />}</FormField>;
}

function AddPasskeyDialog({ onClose, onAdded }: { onClose: () => void; onAdded: () => Promise<void> }) {
  const { t } = useTranslation();
  const notify = useNotify();
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
    <Dialog
      onClose={onClose}
      title={t("passkeys.add")}
      description={t("passkeys.addHint")}
      size="sm"
      onSubmit={(event) => void add(event)}
      footer={
        <>
          <Button onClick={onClose}>{t("connection.cancel")}</Button>
          <Button type="submit" variant="primary" busy={busy}>
            {t("passkeys.confirmAdd")}
          </Button>
        </>
      }
    >
      <FormField label={t("passkeys.name")}>{(ties) => <TextInput {...ties} name="name" required maxLength={100} placeholder={t("passkeys.namePlaceholder")} />}</FormField>
      <PasswordField />
      {error && <Notice tone="error">{error}</Notice>}
    </Dialog>
  );
}

function RemovePasskeyDialog({ passkey, onClose, onRemoved }: { passkey: Passkey; onClose: () => void; onRemoved: () => Promise<void> }) {
  const { t } = useTranslation();
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

  // A dialog, not one that only asks: it is a form that takes the password.
  return (
    <Dialog
      onClose={onClose}
      title={t("passkeys.removeLabel", { name: passkey.name })}
      description={t("passkeys.removeHint")}
      size="sm"
      onSubmit={(event) => void remove(event)}
      footer={
        <>
          <Button onClick={onClose}>{t("connection.cancel")}</Button>
          <Button type="submit" variant="danger-solid" busy={busy}>
            {t("passkeys.remove")}
          </Button>
        </>
      }
    >
      <PasswordField />
      {error && <Notice tone="error">{error}</Notice>}
    </Dialog>
  );
}

/** The household's members, with how many passkeys each has, for its admins to remove (UX-026). */
export function MembersSection() {
  const { t } = useTranslation();
  const users = useQuery({
    queryKey: ["tenant", "users"],
    queryFn: async () => unwrap(await api.GET("/tenant/users", { params: { query: { limit: 100 } } })).items,
  });
  return (
    <Page title={t("members.title")} description={t("members.hint")}>
      {users.isPending && (
        <Card>
          <Loading />
        </Card>
      )}
      {users.data && users.data.length > 0 && (
        <Card>
          <ul aria-label={t("members.title")} className="divide-y divide-line">
            {users.data.map((user) => (
              <Member key={user.id} user={user} />
            ))}
          </ul>
        </Card>
      )}
    </Page>
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
  const { busy, run } = useBusy();

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
    <li>
      <Row
        leading={<Avatar name={user.display_name} />}
        title={<span className="min-w-0 break-words">{user.display_name}</span>}
        description={
          <>
            {user.username}
            {passkeys !== undefined && " · "}
            {passkeys === undefined ? "" : passkeys === 0 ? t("members.noPasskeys") : t("members.passkeys", { count: passkeys })}
          </>
        }
      >
        {passkeys !== undefined && passkeys > 0 && (
          <Button variant="danger" size="sm" aria-label={t("members.removeLabel", { username: user.username })} onClick={() => setConfirming(true)}>
            {t("passkeys.remove")}
          </Button>
        )}
      </Row>
      <Dialog
        asks
        open={confirming}
        onClose={() => setConfirming(false)}
        title={t("members.removeTitle", { name: user.display_name })}
        description={t("members.removeBody", { username: user.username })}
        size="sm"
        footer={
          <>
            <Button onClick={() => setConfirming(false)}>{t("connection.cancel")}</Button>
            <Button variant="danger-solid" busy={busy("remove")} onClick={() => void run("remove", remove)}>
              {t("members.remove")}
            </Button>
          </>
        }
      />
    </li>
  );
}
