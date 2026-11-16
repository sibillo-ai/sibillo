// Remote MCP servers in the app: the household's, their reviewed tools, and each user's account (UX-029, ADR-0099, ADR-0100).
import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Plug, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import { api, ApiError, unwrap, type Schemas } from "../api/client";
import { HOUSEHOLD_MCP_SERVERS, MCP_SERVERS, useHouseholdMcpServers, useMcpServers, type McpServer, type McpServerAuth, type McpServerSummary, type McpServerTool } from "../mcp";
import { useNotify } from "../notices";
import { Switch } from "./AssistantSettings";

const BUTTON = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-hover disabled:opacity-50";
const SMALL = "inline-flex h-8 items-center justify-center rounded-[10px] border border-line-strong bg-surface px-3 text-[13px] font-semibold hover:bg-hover disabled:opacity-50";
const PRIMARY = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg disabled:opacity-50";
const INPUT = "h-10 w-full rounded-[10px] border border-line-strong bg-bg px-3 outline-none focus:border-accent";
const AUTHS: McpServerAuth[] = ["none", "token", "oauth"];

/** What went wrong, from an error of the API: its detail when it gives one. */
function problemText(error: unknown, fallback: string): string {
  if (error instanceof ApiError && typeof error.problem.detail === "string" && error.problem.detail) return error.problem.detail;
  return fallback;
}

function Field(props: { id: string; label: string; hint?: string | undefined; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={props.id} className="text-[13.5px] font-semibold">
        {props.label}
      </label>
      {props.children}
      {props.hint && <small className="text-[12.5px] text-muted">{props.hint}</small>}
    </div>
  );
}

// --- The household's servers, for its admins (AGT-019, AGT-028) ---

/** The household's remote MCP servers: add, review, refresh, switch off and remove them. */
export function McpServersSection() {
  const { t } = useTranslation();
  const servers = useHouseholdMcpServers();
  const queries = useQueryClient();
  const notify = useNotify();
  const heading = useId();
  const [adding, setAdding] = useState(false);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<McpServer | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function changed() {
    await queries.invalidateQueries({ queryKey: HOUSEHOLD_MCP_SERVERS });
    await queries.invalidateQueries({ queryKey: MCP_SERVERS });
  }

  async function refresh(server: McpServer) {
    setBusy(server.id);
    try {
      unwrap(await api.POST("/tenant/mcp-servers/{server_id}/refresh", { params: { path: { server_id: server.id } } }));
      notify({ kind: "info", title: t("mcp.admin.refreshed", { name: server.name }) });
    } catch (error) {
      notify({ kind: "error", title: t("mcp.admin.notRefreshed"), text: problemText(error, t("errors.title")) });
    } finally {
      setBusy(null);
      await changed();
    }
  }

  async function switchServer(server: McpServer, enabled: boolean) {
    try {
      unwrap(await api.PATCH("/tenant/mcp-servers/{server_id}", { params: { path: { server_id: server.id } }, body: { enabled } }));
    } catch (error) {
      notify({ kind: "error", title: t("errors.title"), text: problemText(error, t("assistant.notSaved")) });
    }
    await changed();
  }

  async function remove(server: McpServer) {
    try {
      unwrap(await api.DELETE("/tenant/mcp-servers/{server_id}", { params: { path: { server_id: server.id } } }));
    } catch (error) {
      notify({ kind: "error", title: t("errors.title"), text: problemText(error, t("assistant.notSaved")) });
    }
    setRemoving(null);
    await changed();
  }

  const current = servers.data?.find((server) => server.id === reviewing) ?? null;
  return (
    <section aria-labelledby={heading} className="flex flex-col gap-4">
      <div>
        <h2 id={heading} className="mb-1 text-base font-bold">
          {t("mcp.admin.title")}
        </h2>
        <p className="max-w-[62ch] text-sm text-muted">{t("mcp.admin.hint")}</p>
      </div>
      {servers.data?.length === 0 && <p className="text-sm text-muted">{t("mcp.admin.none")}</p>}
      <ul className="flex flex-col gap-2.5">
        {servers.data?.map((server) => {
          const accepted = server.tools.filter((tool) => tool.status === "accepted").length;
          const changedTools = server.tools.filter((tool) => tool.status === "changed" || tool.status === "gone").length;
          return (
            <li key={server.id} className="flex flex-col gap-2 rounded-[14px] border border-line px-3.5 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <Plug className="size-4 text-muted" aria-hidden="true" />
                <b className="font-semibold">{server.name}</b>
                <code className="font-mono text-[12.5px] text-muted">{server.prefix}__…</code>
                {!server.enabled && <span className="rounded-full bg-hover px-2 py-0.5 text-xs font-semibold">{t("mcp.admin.off")}</span>}
              </div>
              <p className="text-[13px] break-all text-muted">{server.url}</p>
              <p className="text-[13px] text-muted">
                {t(`mcp.auth.${server.auth}`)} · {t("mcp.admin.accepted", { accepted, total: server.tools.length })}
                {changedTools > 0 && <span className="font-semibold text-danger"> · {t("mcp.admin.changedCount", { count: changedTools })}</span>}
              </p>
              {server.auth !== "none" && server.credential !== "valid" && <p className="text-[13px] text-muted">{t("mcp.admin.connectToList")}</p>}
              <div className="flex flex-wrap gap-2">
                <button type="button" className={SMALL} aria-label={t("mcp.admin.reviewLabel", { name: server.name })} onClick={() => setReviewing(server.id)}>
                  {t("mcp.admin.review")}
                </button>
                <button type="button" className={SMALL} disabled={busy === server.id} aria-label={t("mcp.admin.refreshLabel", { name: server.name })} onClick={() => void refresh(server)}>
                  {busy === server.id ? t("mcp.admin.refreshing") : t("mcp.admin.refresh")}
                </button>
                <button type="button" className={SMALL} onClick={() => void switchServer(server, !server.enabled)}>
                  {server.enabled ? t("mcp.admin.switchOff") : t("mcp.admin.switchOn")}
                </button>
                <button type="button" className={SMALL} aria-label={t("mcp.admin.removeLabel", { name: server.name })} onClick={() => setRemoving(server)}>
                  {t("settings.remove")}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
      <div>
        <button type="button" className={BUTTON} onClick={() => setAdding(true)}>
          {t("mcp.admin.add")}
        </button>
      </div>
      {adding && <AddServerDialog onClose={() => setAdding(false)} onAdded={async () => (setAdding(false), await changed())} />}
      {current && <ReviewDialog key={current.id} server={current} onClose={() => setReviewing(null)} onSaved={changed} />}
      <Dialog.Root open={removing !== null} onOpenChange={(open) => !open && setRemoving(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
          <Dialog.Content role="alertdialog" className="rise fixed top-1/2 left-1/2 z-50 w-[min(92vw,28rem)] -translate-x-1/2 -translate-y-1/2 rounded-[20px] bg-raised p-[22px] shadow-soft">
            <Dialog.Title className="mb-2 text-lg font-bold">{t("mcp.admin.removeTitle", { name: removing?.name ?? "" })}</Dialog.Title>
            <Dialog.Description className="text-muted">{t("mcp.admin.removeBody")}</Dialog.Description>
            <div className="mt-[18px] flex justify-end gap-2">
              <Dialog.Close className={BUTTON}>{t("connection.cancel")}</Dialog.Close>
              <button type="button" className="h-[38px] rounded-[10px] bg-danger px-4 text-sm font-semibold text-on-danger" onClick={() => removing && void remove(removing)}>
                {t("settings.remove")}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </section>
  );
}

function AddServerDialog({ onClose, onAdded }: { onClose: () => void; onAdded: () => Promise<void> }) {
  const { t } = useTranslation();
  const [auth, setAuth] = useState<McpServerAuth>("none");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function add(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim();
    const clientId = text("oauth_client_id");
    const clientSecret = text("oauth_client_secret");
    setBusy(true);
    setProblem(null);
    try {
      unwrap(
        await api.POST("/tenant/mcp-servers", {
          body: {
            name: text("name"),
            prefix: text("prefix"),
            url: text("url"),
            auth,
            ...(auth === "oauth" && clientId ? { oauth_client_id: clientId } : {}),
            ...(auth === "oauth" && clientId && clientSecret ? { oauth_client_secret: clientSecret } : {}),
          },
        }),
      );
      await onAdded();
    } catch (error) {
      setProblem(problemText(error, error instanceof ApiError && error.status === 409 ? t("mcp.admin.taken") : t("mcp.admin.notAdded")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className="rise fixed top-1/2 left-1/2 z-50 max-h-[calc(100%-2rem)] w-[min(92vw,30rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[20px] bg-raised p-[22px] shadow-soft">
          <Dialog.Title className="mb-1 text-lg font-bold">{t("mcp.admin.addTitle")}</Dialog.Title>
          <Dialog.Description className="mb-3 text-sm text-muted">{t("mcp.admin.addHint")}</Dialog.Description>
          <form onSubmit={(event) => void add(event)} className="flex flex-col gap-3.5">
            <Field id="mcp-name" label={t("mcp.admin.name")}>
              <input id="mcp-name" name="name" required maxLength={100} className={INPUT} />
            </Field>
            <Field id="mcp-prefix" label={t("mcp.admin.prefix")} hint={t("mcp.admin.prefixHint")}>
              <input id="mcp-prefix" name="prefix" required maxLength={20} pattern="[a-z][a-z0-9]*(_[a-z0-9]+)*" autoComplete="off" className={`${INPUT} font-mono`} />
            </Field>
            <Field id="mcp-url" label={t("mcp.admin.address")} hint={t("mcp.admin.addressHint")}>
              <input id="mcp-url" name="url" type="url" required className={INPUT} />
            </Field>
            <Field id="mcp-auth" label={t("mcp.admin.signIn")} hint={t(`mcp.admin.authHints.${auth}`)}>
              <select id="mcp-auth" value={auth} onChange={(event) => setAuth(event.target.value as McpServerAuth)} className={INPUT}>
                {AUTHS.map((item) => (
                  <option key={item} value={item}>
                    {t(`mcp.auth.${item}`)}
                  </option>
                ))}
              </select>
            </Field>
            {auth === "oauth" && (
              <>
                <Field id="mcp-client" label={t("mcp.admin.clientId")} hint={t("mcp.admin.clientIdHint")}>
                  <input id="mcp-client" name="oauth_client_id" autoComplete="off" className={INPUT} />
                </Field>
                <Field id="mcp-secret" label={t("mcp.admin.clientSecret")}>
                  <input id="mcp-secret" name="oauth_client_secret" type="password" autoComplete="off" className={INPUT} />
                </Field>
              </>
            )}
            {busy && (
              <p role="status" className="live-text text-sm">
                {t("mcp.admin.connecting")}
              </p>
            )}
            {problem && (
              <p role="alert" className="text-sm text-danger">
                {problem}
              </p>
            )}
            <div className="mt-1 flex justify-end gap-2">
              <Dialog.Close className={BUTTON}>{t("connection.cancel")}</Dialog.Close>
              <button type="submit" className={PRIMARY} disabled={busy}>
                {t("mcp.admin.addButton")}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ToolDetails({ tool }: { tool: McpServerTool }) {
  const { t } = useTranslation();
  const listed = tool.listed;
  const accepted = tool.accepted;
  return (
    <div className="flex flex-col gap-1.5 text-[13px]">
      <code className="font-mono text-[12.5px] text-muted">{tool.model_name}</code>
      {tool.status === "changed" && accepted && (
        <div className="rounded-[10px] bg-hover px-2.5 py-2">
          <p className="font-semibold">{t("mcp.review.whenAccepted")}</p>
          <p className="whitespace-pre-wrap">{accepted.description}</p>
        </div>
      )}
      {listed ? (
        <>
          {tool.status === "changed" && <p className="font-semibold">{t("mcp.review.now")}</p>}
          <p className="whitespace-pre-wrap">{listed.description || t("mcp.review.noDescription")}</p>
          <details>
            <summary className="cursor-pointer font-semibold text-muted">{t("mcp.review.schema")}</summary>
            <pre className="mt-1 max-h-60 overflow-auto rounded-lg bg-hover p-2 font-mono text-[12px]">{JSON.stringify(listed.input_schema, null, 2)}</pre>
          </details>
          {listed.annotations && Object.keys(listed.annotations).length > 0 && (
            <p className="text-muted">
              {t("mcp.review.hints")} <code className="font-mono text-[12px]">{JSON.stringify(listed.annotations)}</code>
            </p>
          )}
        </>
      ) : (
        <p className="text-muted">{t("mcp.review.goneHint")}</p>
      )}
    </div>
  );
}

/** Every tool a server lists, each accepted or not by the admin, as the model would read it (AGT-028). */
function ReviewDialog({ server, onClose, onSaved }: { server: McpServer; onClose: () => void; onSaved: () => Promise<void> }) {
  const { t } = useTranslation();
  const notify = useNotify();
  const [chosen, setChosen] = useState(() => new Set(server.tools.filter((tool) => tool.status === "accepted").map((tool) => tool.name)));
  const [busy, setBusy] = useState(false);

  function toggle(name: string, on: boolean) {
    const next = new Set(chosen);
    if (on) next.add(name);
    else next.delete(name);
    setChosen(next);
  }

  async function save() {
    setBusy(true);
    const tools = server.tools.filter((tool) => chosen.has(tool.name) && tool.digest !== null).map((tool) => ({ name: tool.name, digest: tool.digest ?? "" }));
    try {
      unwrap(await api.PUT("/tenant/mcp-servers/{server_id}/accepted-tools", { params: { path: { server_id: server.id } }, body: { tools } }));
      await onSaved();
      onClose();
    } catch (error) {
      notify({ kind: "error", title: t("mcp.review.notSaved"), text: problemText(error, t("mcp.review.listedAgain")) });
      await onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className="rise fixed top-1/2 left-1/2 z-50 flex max-h-[min(92dvh,48rem)] w-[min(94vw,40rem)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-[20px] bg-raised text-fg shadow-soft">
          <div className="flex items-start justify-between gap-3 px-[22px] pt-[22px]">
            <div>
              <Dialog.Title className="text-lg font-bold tracking-tight">{t("mcp.review.title", { name: server.name })}</Dialog.Title>
              <Dialog.Description className="max-w-[60ch] text-sm text-muted">{t("mcp.review.hint")}</Dialog.Description>
            </div>
            <Dialog.Close className="grid size-9 flex-none place-items-center rounded-[10px] text-muted hover:bg-hover hover:text-fg" aria-label={t("files.close")}>
              <X className="size-5" aria-hidden="true" />
            </Dialog.Close>
          </div>
          <ul className="flex min-h-0 flex-col gap-2.5 overflow-y-auto px-[22px] py-4">
            {server.tools.length === 0 && <li className="text-sm text-muted">{t("mcp.review.noTools")}</li>}
            {server.tools.map((tool) => {
              const label = tool.listed?.title ?? tool.accepted?.title ?? tool.name;
              const usable = tool.listed !== null && tool.problem === null;
              return (
                <li key={tool.name} className="flex gap-3 rounded-[14px] border border-line px-3 py-2.5">
                  <input
                    type="checkbox"
                    className="mt-1 size-4 flex-none"
                    aria-label={t("mcp.review.accept", { name: label })}
                    checked={usable && chosen.has(tool.name)}
                    disabled={!usable}
                    onChange={(event) => toggle(tool.name, event.target.checked)}
                  />
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <b className="font-semibold">{label}</b>
                      {tool.status !== "not_accepted" && (
                        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${tool.status === "accepted" ? "bg-accent-soft text-accent" : "bg-danger/15 text-danger"}`}>{t(`mcp.review.status.${tool.status}`)}</span>
                      )}
                      {tool.problem && <span className="text-xs text-danger">{t(`mcp.review.problems.${tool.problem}`)}</span>}
                    </div>
                    <ToolDetails tool={tool} />
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="flex justify-end gap-2 border-t border-line px-[22px] py-3.5">
            <Dialog.Close className={BUTTON}>{t("conversationMenu.cancel")}</Dialog.Close>
            <button type="button" className={PRIMARY} disabled={busy} onClick={() => void save()}>
              {t("conversationMenu.save")}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// --- Each user's account (AGT-030, AGT-031) ---

/** The household's services, and the user's account on each: connect a token, sign in, or disconnect. */
export function ServicesSection() {
  const { t } = useTranslation();
  const servers = useMcpServers();
  const heading = useId();
  return (
    <section aria-labelledby={heading} className="flex flex-col gap-4">
      <div>
        <h2 id={heading} className="mb-1 text-base font-bold">
          {t("mcp.services.title")}
        </h2>
        <p className="max-w-[62ch] text-sm text-muted">{t("mcp.services.hint")}</p>
      </div>
      {servers.data?.length === 0 && <p className="text-sm text-muted">{t("mcp.services.none")}</p>}
      {servers.data?.map((server) => <Service key={server.id} server={server} />)}
    </section>
  );
}

function Service({ server }: { server: McpServerSummary }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const heading = useId();
  const tokenId = useId();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);

  async function changed() {
    await queries.invalidateQueries({ queryKey: MCP_SERVERS });
    await queries.invalidateQueries({ queryKey: HOUSEHOLD_MCP_SERVERS });
  }

  async function connect(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      unwrap(await api.PUT("/mcp-servers/{server_id}/credential", { params: { path: { server_id: server.id } }, body: { token } }));
      setToken("");
      await changed();
    } catch (error) {
      notify({ kind: "error", title: t("mcp.services.notConnectedError"), text: problemText(error, t("errors.title")) });
    } finally {
      setBusy(false);
    }
  }

  async function signIn() {
    setBusy(true);
    try {
      const started = unwrap(await api.POST("/mcp-servers/{server_id}/sign-in", { params: { path: { server_id: server.id } } }));
      window.location.assign(started.authorization_url);
    } catch (error) {
      notify({ kind: "error", title: t("mcp.services.notConnectedError"), text: problemText(error, t("errors.title")) });
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      unwrap(await api.DELETE("/mcp-servers/{server_id}/credential", { params: { path: { server_id: server.id } } }));
      await changed();
    } finally {
      setBusy(false);
    }
  }

  const connected = server.credential === "valid";
  return (
    <section aria-labelledby={heading} className="flex max-w-[560px] flex-col gap-2 rounded-[14px] border border-line px-3.5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <Plug className="size-4 text-muted" aria-hidden="true" />
        <h3 id={heading} className="font-semibold">
          {server.name}
        </h3>
        <span className="text-[13px] text-muted">{server.host}</span>
      </div>
      {server.tools.length > 0 && <p className="text-[13px] text-muted">{t("mcp.services.tools", { tools: server.tools.map((tool) => tool.title ?? tool.model_name).join(", ") })}</p>}
      {server.denied ? (
        <p className="text-sm">{t("permissions.lockedByAdmin")}</p>
      ) : server.auth === "none" ? (
        <p className="text-sm">{t("mcp.services.noAccount")}</p>
      ) : (
        <>
          <p className="text-sm font-semibold">{t(`mcp.services.state.${server.credential}`)}</p>
          {server.auth === "token" && (
            <form onSubmit={(event) => void connect(event)} className="flex flex-col gap-1.5">
              <label htmlFor={tokenId} className="text-[13.5px] font-semibold">
                {t("mcp.services.token")}
              </label>
              <div className="flex gap-2">
                <input id={tokenId} type="password" autoComplete="off" required value={token} onChange={(event) => setToken(event.target.value)} className={INPUT} />
                <button type="submit" className={PRIMARY} disabled={busy}>
                  {t("mcp.services.connect")}
                </button>
              </div>
              <small className="text-[12.5px] text-muted">{t("mcp.services.leastRights")}</small>
            </form>
          )}
          {server.auth === "oauth" && !connected && (
            <div>
              <button type="button" className={PRIMARY} disabled={busy} onClick={() => void signIn()}>
                {t("mcp.services.signIn")}
              </button>
            </div>
          )}
          {server.credential !== "missing" && (
            <div className="flex flex-col gap-1">
              <div>
                <button type="button" className={SMALL} disabled={busy} onClick={() => void disconnect()}>
                  {t("mcp.services.disconnect")}
                </button>
              </div>
              {server.auth === "oauth" && <small className="text-[12.5px] text-muted">{t("mcp.services.revokeHint")}</small>}
            </div>
          )}
        </>
      )}
    </section>
  );
}

/** Where a sign-in to a service comes back: completes it, then shows the services (ADR-0100, point 4). */
export function McpSignIn() {
  const { t } = useTranslation();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const queries = useQueryClient();
  const notify = useNotify();
  const started = useRef(false);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    // Once, even when React runs effects twice: a sign-in is used once.
    if (started.current) return;
    started.current = true;
    const state = search.get("state");
    void (async () => {
      try {
        if (!state) throw new Error("no state");
        // What the redirect carried, as it carried it (ADR-0100, point 5).
        const body: Schemas["CompleteMcpSignInRequest"] = { state };
        for (const name of ["code", "iss", "error", "error_description"] as const) {
          const found = search.get(name);
          if (found) body[name] = found;
        }
        const server = unwrap(await api.POST("/mcp-sign-in", { body }));
        await queries.invalidateQueries({ queryKey: MCP_SERVERS });
        notify({ kind: "info", title: t("mcp.services.signedIn", { name: server.name }) });
        await navigate("/settings?section=services", { replace: true });
      } catch (error) {
        setFailed(problemText(error, t("mcp.services.signInFailed")));
      }
    })();
  }, [search, navigate, queries, notify, t]);

  return (
    <div className="mx-auto flex max-w-[40rem] flex-col gap-3 p-6">
      <h1 className="text-[22px] font-bold">{t("mcp.services.signingIn")}</h1>
      {failed ? (
        <>
          <p role="alert" className="text-danger">
            {failed}
          </p>
          <div>
            <button type="button" className={BUTTON} onClick={() => void navigate("/settings?section=services", { replace: true })}>
              {t("mcp.services.back")}
            </button>
          </div>
        </>
      ) : (
        <p role="status" className="live-text text-muted">
          {t("mcp.services.completing")}
        </p>
      )}
    </div>
  );
}

// --- Switches (AGT-029) ---

/** One switch per server, with its tools, beside the tool switches; a denied server is off and locked (ADR-0099). */
export function ServerSwitches({ off, onChange }: { off: string[]; onChange: (off: string[]) => void }) {
  const { t } = useTranslation();
  const servers = useMcpServers();
  const heading = useId();
  if (!servers.data || servers.data.length === 0) return null;
  const isOn = (server: McpServerSummary) => !off.includes(server.id) && !server.denied;
  return (
    <div role="group" aria-labelledby={heading}>
      <h3 id={heading} className="mb-1 text-sm font-bold">
        {t("mcp.switches.title")}
      </h3>
      <p className="mb-2.5 max-w-[62ch] text-sm text-muted">{t("mcp.switches.hint")}</p>
      <div className="flex flex-col gap-3">
        {servers.data.map((server) => (
          <div key={server.id} className="max-w-[460px] rounded-[14px] border border-line px-2.5 py-1.5">
            <Switch
              label={server.name}
              description={
                <>
                  {server.tools.length > 0 ? server.tools.map((tool) => tool.title ?? tool.model_name).join(", ") : t("mcp.switches.noTools")}
                  {server.denied && <span className="block">{t("permissions.lockedByAdmin")}</span>}
                  {!server.denied && server.auth !== "none" && server.credential !== "valid" && <span className="block">{t("mcp.switches.notConnected")}</span>}
                </>
              }
              checked={isOn(server)}
              locked={server.denied}
              strong
              onChange={(checked) => onChange(checked ? off.filter((id) => id !== server.id) : [...off.filter((id) => id !== server.id), server.id])}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
