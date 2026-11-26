// The household's members for its admins: adding them, their account, their budget and usage (UX-044, UX-045,
// UX-026, AUTH-002, AUTH-008, AUTH-013, AUTH-014, MOD-004, MOD-021, ADR-0144, ADR-0145).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, UserPlus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { ApiError, api, unwrap, type Schemas, type User } from "../api/client";
import { useBusy } from "../busy";
import { USAGE } from "../costs";
import { useNotify } from "../notices";
import { Avatar, Badge, Button, Card, Dialog, FormField, Group, Loading, Notice, Page, Row, Select, TextInput } from "../ui";
import { deviceTimeZone, useMemberUsage } from "../usage";
import { UsageView } from "./UsageSettings";

type Budget = Schemas["Budget"];
type BudgetPeriod = Schemas["BudgetPeriod"];

const USERS = ["tenant", "users"] as const;
const PERIODS: BudgetPeriod[] = ["day", "week", "month"];
// The currency of a cost limit: the one remote providers report their prices in (ADR-0057).
const CURRENCY = "USD";

function useUsers() {
  return useQuery({
    queryKey: USERS,
    queryFn: async () => unwrap(await api.GET("/tenant/users", { params: { query: { limit: 100 } } })).items,
  });
}

/** What the admin may change of an account: never their own, nor an instance admin's unless they are one (AUTH-008). */
function mayChange(me: User, user: User): boolean {
  return user.id !== me.id && (!user.instance_admin || me.instance_admin);
}

/** The household's members, and the page of the one the address names. */
export function MembersSection({ me }: { me: User }) {
  const { t } = useTranslation();
  const [search, setSearch] = useSearchParams();
  const users = useUsers();
  const [adding, setAdding] = useState(false);
  const chosen = search.get("member");
  const open = (id: string | null) => setSearch(id ? { section: "members", member: id } : { section: "members" });
  const member = users.data?.find((user) => user.id === chosen);
  if (chosen && member) return <MemberPage me={me} user={member} onBack={() => open(null)} />;
  return (
    <Page title={t("members.title")} description={t("members.hint")}>
      <Group
        title={t("members.list")}
        action={
          <Button size="sm" onClick={() => setAdding(true)}>
            <UserPlus aria-hidden="true" />
            {t("members.add")}
          </Button>
        }
      >
        {users.isPending ? (
          <Card>
            <Loading />
          </Card>
        ) : (
          <Card>
            <ul aria-label={t("members.title")} className="divide-y divide-line">
              {(users.data ?? []).map((user) => (
                <MemberRow key={user.id} me={me} user={user} onOpen={() => open(user.id)} />
              ))}
            </ul>
          </Card>
        )}
      </Group>
      {adding && <AddMemberDialog onClose={() => setAdding(false)} />}
    </Page>
  );
}

/** A member in the list: their name and role, how many passkeys they have, for the admin to remove (UX-026), and their page. */
function MemberRow({ me, user, onOpen }: { me: User; user: User; onOpen: () => void }) {
  const { t } = useTranslation();
  const passkeys = usePasskeys(user);
  return (
                <li>
                  <Row
                    leading={<Avatar name={user.display_name} />}
                    title={
                      <span className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="min-w-0 break-words">{user.display_name}</span>
                        {user.id === me.id && <Badge>{t("members.you")}</Badge>}
                        {user.role === "tenant_admin" && <Badge tone="accent">{t("members.roles.tenant_admin")}</Badge>}
                        {user.disabled && <Badge tone="warn">{t("members.disabled")}</Badge>}
                      </span>
                    }
                    description={
                      <>
                        {user.username}
                        {passkeys.count !== undefined && " · "}
                        {passkeys.count === undefined ? "" : passkeys.count === 0 ? t("members.noPasskeys") : t("members.passkeys", { count: passkeys.count })}
                      </>
                    }
                  >
                    <span className="flex flex-wrap justify-end gap-2">
                      {mayChange(me, user) && passkeys.count !== undefined && passkeys.count > 0 && passkeys.removeButton}
                      <Button size="sm" aria-label={t("members.manage", { username: user.username })} onClick={onOpen}>
                        {t("members.open")}
                      </Button>
                    </span>
                  </Row>
                  {passkeys.dialog}
                </li>
  );
}

function AddMemberDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const role = form.get("role") === "tenant_admin" ? "tenant_admin" : "member";
      const created = unwrap(
        await api.POST("/tenant/users", {
          body: {
            username: String(form.get("username") ?? "").trim(),
            display_name: String(form.get("display_name") ?? "").trim(),
            password: String(form.get("password") ?? ""),
            role,
          },
        }),
      );
      await queries.invalidateQueries({ queryKey: USERS });
      notify({ kind: "info", title: t("members.added", { name: created.display_name }) });
      onClose();
    } catch (failure) {
      setError(failure instanceof ApiError && failure.code === "resource.conflict" ? t("members.taken") : failure instanceof ApiError && failure.status === 422 ? t("members.invalid") : t("errors.internal_error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      onClose={onClose}
      title={t("members.add")}
      description={t("members.addHint")}
      size="sm"
      onSubmit={(event) => void add(event)}
      footer={
        <>
          <Button onClick={onClose}>{t("connection.cancel")}</Button>
          <Button type="submit" variant="primary" busy={busy}>
            {t("members.addButton")}
          </Button>
        </>
      }
    >
      <FormField label={t("members.username")} hint={t("members.usernameHint")}>
        {(ties) => <TextInput {...ties} name="username" required autoComplete="off" autoCapitalize="none" spellCheck={false} pattern="[a-z0-9][a-z0-9._\-]{1,63}" maxLength={64} />}
      </FormField>
      <FormField label={t("members.name")}>{(ties) => <TextInput {...ties} name="display_name" required maxLength={100} autoComplete="off" />}</FormField>
      <FormField label={t("members.initialPassword")} hint={t("members.initialPasswordHint")}>
        {(ties) => <TextInput {...ties} name="password" type="password" required minLength={12} maxLength={1024} autoComplete="new-password" />}
      </FormField>
      <FormField label={t("members.role")}>
        {(ties) => (
          <Select {...ties} name="role" defaultValue="member">
            <option value="member">{t("members.roles.member")}</option>
            <option value="tenant_admin">{t("members.roles.tenant_admin")}</option>
          </Select>
        )}
      </FormField>
      {error && <Notice tone="error">{error}</Notice>}
    </Dialog>
  );
}

/** One member: their account, their passkeys, their budget and usage, and the deletion of their account. */
function MemberPage({ me, user, onBack }: { me: User; user: User; onBack: () => void }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const { busy, run } = useBusy();
  const changeable = mayChange(me, user);
  const [resetting, setResetting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const usage = useMemberUsage(user.id);

  async function change(body: Schemas["UpdateUserRequest"]) {
    const result = await api.PATCH("/tenant/users/{user_id}", { params: { path: { user_id: user.id } }, body });
    if (!result.response.ok) {
      const failure = result.error as { code?: string } | undefined;
      notify({ kind: "error", title: t("errors.title"), text: failure?.code === "resource.conflict" ? t("members.lastAdmin") : t("errors.internal_error") });
      return;
    }
    await queries.invalidateQueries({ queryKey: USERS });
  }

  async function remove() {
    const result = await api.DELETE("/tenant/users/{user_id}", { params: { path: { user_id: user.id } } });
    setDeleting(false);
    if (!result.response.ok) {
      const failure = result.error as { code?: string } | undefined;
      notify({ kind: "error", title: t("errors.title"), text: failure?.code === "run.in_progress" ? t("members.deleteBusy") : t("errors.internal_error") });
      return;
    }
    notify({ kind: "info", title: t("members.deleted", { name: user.display_name }) });
    await queries.invalidateQueries({ queryKey: USERS });
    onBack();
  }

  return (
    <Page title={user.display_name} description={user.username}>
      <div>
        <Button size="sm" variant="ghost" onClick={onBack}>
          <ChevronLeft className="rtl:-scale-x-100" aria-hidden="true" />
          {t("members.back")}
        </Button>
      </div>
      <Group title={t("members.account")}>
        <Card rows>
          {changeable && (
            <Row title={t("members.role")} htmlFor={`role-${user.id}`} wide>
              <Select id={`role-${user.id}`} value={user.role} onChange={(event) => void change({ role: event.target.value === "tenant_admin" ? "tenant_admin" : "member" })}>
                <option value="member">{t("members.roles.member")}</option>
                <option value="tenant_admin">{t("members.roles.tenant_admin")}</option>
              </Select>
            </Row>
          )}
          <Row title={t("members.state")} description={user.disabled ? t("members.stateDisabled") : t("members.stateEnabled")}>
            {changeable && (
              <Button size="sm" busy={busy("state")} onClick={() => void run("state", () => change({ disabled: !user.disabled }))}>
                {user.disabled ? t("members.enable") : t("members.disable")}
              </Button>
            )}
          </Row>
          {changeable && (
            <Row title={t("members.password")} description={t("members.passwordHint")}>
              <Button size="sm" onClick={() => setResetting(true)}>
                {t("members.reset")}
              </Button>
            </Row>
          )}
          <PasskeysRow me={me} user={user} />
        </Card>
      </Group>
      <BudgetGroup user={user} />
      <Group title={t("usage.title")} role="group">
        {usage.data ? <UsageView overview={usage.data} /> : <Card>{usage.isError ? <p className="p-4 text-small text-ink-2">{t("errors.internal_error")}</p> : <Loading />}</Card>}
      </Group>
      {user.id !== me.id && !user.instance_admin && (
        <Group title={t("members.deleteGroup")}>
          <Card>
            <Row title={t("members.delete")} description={user.disabled ? t("members.deleteHint") : t("members.deleteNeedsDisable")}>
              <Button size="sm" variant="danger" disabled={!user.disabled} onClick={() => setDeleting(true)}>
                {t("members.delete")}
              </Button>
            </Row>
          </Card>
        </Group>
      )}
      {resetting && <ResetPasswordDialog user={user} onClose={() => setResetting(false)} />}
      <Dialog
        asks
        open={deleting}
        onClose={() => setDeleting(false)}
        title={t("members.deleteTitle", { name: user.display_name })}
        description={t("members.deleteBody", { name: user.display_name })}
        size="sm"
        footer={
          <>
            <Button onClick={() => setDeleting(false)}>{t("connection.cancel")}</Button>
            <Button variant="danger-solid" busy={busy("delete")} onClick={() => void run("delete", remove)}>
              {t("members.delete")}
            </Button>
          </>
        }
      />
    </Page>
  );
}

function ResetPasswordDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const { t } = useTranslation();
  const notify = useNotify();
  const queries = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function reset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      unwrap(await api.POST("/tenant/users/{user_id}/password", { params: { path: { user_id: user.id } }, body: { password: String(form.get("password") ?? "") } }));
      await queries.invalidateQueries({ queryKey: USERS });
      notify({ kind: "info", title: t("members.passwordSet") });
      onClose();
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 422 ? t("members.invalid") : t("errors.internal_error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      onClose={onClose}
      title={t("members.resetTitle", { name: user.display_name })}
      description={t("members.resetHint", { name: user.display_name })}
      size="sm"
      onSubmit={(event) => void reset(event)}
      footer={
        <>
          <Button onClick={onClose}>{t("connection.cancel")}</Button>
          <Button type="submit" variant="primary" busy={busy}>
            {t("members.setPassword")}
          </Button>
        </>
      }
    >
      <FormField label={t("members.newPassword")} hint={t("members.initialPasswordHint")}>
        {(ties) => <TextInput {...ties} name="password" type="password" required minLength={12} maxLength={1024} autoComplete="new-password" />}
      </FormField>
      {error && <Notice tone="error">{error}</Notice>}
    </Dialog>
  );
}

/** How many passkeys a member has, and a button that removes them all after a confirmation (UX-026). */
function usePasskeys(user: User) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const key = [...USERS, user.id, "passkeys"];
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

  return {
    count: count.data,
    removeButton: (
      <Button variant="danger" size="sm" aria-label={t("members.removeLabel", { username: user.username })} onClick={() => setConfirming(true)}>
        {t("passkeys.remove")}
      </Button>
    ),
    dialog: (
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
    ),
  };
}

/** The member's passkeys on their page. */
function PasskeysRow({ me, user }: { me: User; user: User }) {
  const { t } = useTranslation();
  const passkeys = usePasskeys(user);
  const count = passkeys.count;
  return (
    <Row title={t("members.passkeysRow")} description={count === undefined ? "" : count === 0 ? t("members.noPasskeys") : t("members.passkeys", { count })}>
      {mayChange(me, user) && count !== undefined && count > 0 && passkeys.removeButton}
      {passkeys.dialog}
    </Row>
  );
}

/** The member's cost and token limits, each over a period of the admin's time zone (MOD-004, ADR-0145). */
function BudgetGroup({ user }: { user: User }) {
  const { t } = useTranslation();
  const key = [...USERS, user.id, "budget"];
  const budget = useQuery({
    queryKey: key,
    queryFn: async () => unwrap(await api.GET("/tenant/users/{user_id}/budget", { params: { path: { user_id: user.id } } })),
  });
  return (
    <Group title={t("budget.title")} description={t("budget.hint", { name: user.display_name, zone: deviceTimeZone() })}>
      {budget.data ? <BudgetForm user={user} budget={budget.data} /> : <Card>{<Loading />}</Card>}
    </Group>
  );
}

function BudgetForm({ user, budget }: { user: User; budget: Budget }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const [cost, setCost] = useState(budget.cost?.amount ?? "");
  const [costPeriod, setCostPeriod] = useState<BudgetPeriod>(budget.cost?.period ?? "month");
  const [tokens, setTokens] = useState(budget.tokens ? String(budget.tokens.tokens) : "");
  const [tokensPeriod, setTokensPeriod] = useState<BudgetPeriod>(budget.tokens?.period ?? "day");
  const [state, setState] = useState<"saved" | "invalid" | "failed" | null>(null);
  const { busy, run } = useBusy();

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const zone = deviceTimeZone();
    const amount = cost.trim().replace(",", ".");
    const count = tokens.trim();
    if ((amount && !/^\d{1,12}(\.\d{1,4})?$/.test(amount)) || (amount && Number(amount) <= 0) || (count && !/^[1-9]\d{0,12}$/.test(count))) {
      setState("invalid");
      return;
    }
    const body: Budget = {
      cost: amount ? { amount, currency: budget.cost?.currency ?? CURRENCY, period: costPeriod, time_zone: budget.cost && budget.cost.period === costPeriod && budget.cost.amount === amount ? budget.cost.time_zone : zone } : null,
      tokens: count ? { tokens: Number(count), period: tokensPeriod, time_zone: budget.tokens && budget.tokens.period === tokensPeriod && String(budget.tokens.tokens) === count ? budget.tokens.time_zone : zone } : null,
    };
    const result = await api.PUT("/tenant/users/{user_id}/budget", { params: { path: { user_id: user.id } }, body });
    if (!result.response.ok) {
      setState(result.response.status === 422 ? "invalid" : "failed");
      return;
    }
    setState("saved");
    await queries.invalidateQueries({ queryKey: [...USERS, user.id, "budget"] });
    await queries.invalidateQueries({ queryKey: USAGE });
  }

  const periods = PERIODS.map((period) => (
    <option key={period} value={period}>
      {t(`budget.periods.${period}`)}
    </option>
  ));
  return (
    <form onSubmit={(event) => void run("save", () => save(event))} className="flex flex-col gap-3">
      <Card rows>
        <Row title={t("budget.cost", { currency: budget.cost?.currency ?? CURRENCY })} description={t("budget.costHint")} htmlFor={`cost-${user.id}`}>
          <TextInput id={`cost-${user.id}`} inputMode="decimal" value={cost} onChange={(event) => setCost(event.target.value)} placeholder={t("budget.none")} />
        </Row>
        <Row title={t("budget.costPeriod")} htmlFor={`cost-period-${user.id}`} wide>
          <Select id={`cost-period-${user.id}`} value={costPeriod} onChange={(event) => setCostPeriod(event.target.value as BudgetPeriod)}>
            {periods}
          </Select>
        </Row>
        <Row title={t("budget.tokens")} description={t("budget.tokensHint")} htmlFor={`tokens-${user.id}`}>
          <TextInput id={`tokens-${user.id}`} inputMode="numeric" value={tokens} onChange={(event) => setTokens(event.target.value)} placeholder={t("budget.none")} />
        </Row>
        <Row title={t("budget.tokensPeriod")} htmlFor={`tokens-period-${user.id}`} wide>
          <Select id={`tokens-period-${user.id}`} value={tokensPeriod} onChange={(event) => setTokensPeriod(event.target.value as BudgetPeriod)}>
            {periods}
          </Select>
        </Row>
      </Card>
      <div className="flex flex-wrap items-center justify-end gap-3">
        {state && (
          <span role={state === "saved" ? "status" : "alert"} className={state === "saved" ? "text-small text-ok" : "text-small text-danger"}>
            {t(`budget.${state}`)}
          </span>
        )}
        <Button type="submit" variant="primary" busy={busy("save")}>
          {t("budget.save")}
        </Button>
      </div>
    </form>
  );
}
