// Remote MCP servers in the app: the household's, their reviewed tools, and each user's account (UX-029, ADR-0099, ADR-0100).
import { useQueryClient } from "@tanstack/react-query";
import { Plug, Plus } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { api, ApiError, ok, unwrap, type Schemas } from "../api/client";
import { HOUSEHOLD_MCP_SERVERS, MCP_SERVERS, useHouseholdMcpServers, useMcpServers, type McpServer, type McpServerAuth, type McpServerSummary, type McpServerTool } from "../mcp";
import { useBusy } from "../busy";
import { useNotify } from "../notices";
import { Badge, Button, Card, Checkbox, Dialog, EmptyState, FormField, Loading, Notice, Page, Row, Select, TextInput, Tile, TopBar } from "../ui";
import { MenuButton } from "./Shell";
import { Switch } from "./AssistantSettings";

const AUTHS: McpServerAuth[] = ["none", "token", "oauth"];

/** What went wrong, from an error of the API: its detail when it gives one. */
function problemText(error: unknown, fallback: string): string {
  if (error instanceof ApiError && typeof error.problem.detail === "string" && error.problem.detail) return error.problem.detail;
  return fallback;
}

// --- The household's servers, for its admins (AGT-019, AGT-028) ---

/** The household's remote MCP servers: add, review, refresh, switch off and remove them. */
export function McpServersSection() {
  const { t } = useTranslation();
  const servers = useHouseholdMcpServers();
  const queries = useQueryClient();
  const notify = useNotify();
  const [adding, setAdding] = useState(false);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<McpServer | null>(null);
  const { busy, run } = useBusy();

  async function changed() {
    await queries.invalidateQueries({ queryKey: HOUSEHOLD_MCP_SERVERS });
    await queries.invalidateQueries({ queryKey: MCP_SERVERS });
  }

  async function refresh(server: McpServer) {
    try {
      unwrap(await api.POST("/tenant/mcp-servers/{server_id}/refresh", { params: { path: { server_id: server.id } } }));
      notify({ kind: "info", title: t("mcp.admin.refreshed", { name: server.name }) });
    } catch (error) {
      notify({ kind: "error", title: t("mcp.admin.notRefreshed"), text: problemText(error, t("errors.title")) });
    } finally {
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
      ok(await api.DELETE("/tenant/mcp-servers/{server_id}", { params: { path: { server_id: server.id } } }));
    } catch (error) {
      notify({ kind: "error", title: t("errors.title"), text: problemText(error, t("assistant.notSaved")) });
    }
    setRemoving(null);
    await changed();
  }

  const current = servers.data?.find((server) => server.id === reviewing) ?? null;
  const add = (
    <Button onClick={() => setAdding(true)}>
      <Plus aria-hidden="true" />
      {t("mcp.admin.add")}
    </Button>
  );
  return (
    <Page title={t("mcp.admin.title")} description={t("mcp.admin.hint")}>
      <div className="flex flex-col items-start gap-3">
        {servers.isPending && (
          <div className="w-full">
            <Card>
              <Loading />
            </Card>
          </div>
        )}
        {servers.data && (
          <div className="w-full">
            <Card rows>
              {servers.data.length === 0 && (
                <EmptyState icon={<Plug />} title={t("mcp.admin.none")} action={add}>
                  {t("mcp.admin.noneHint")}
                </EmptyState>
              )}
              {servers.data.map((server) => {
                const accepted = server.tools.filter((tool) => tool.status === "accepted").length;
                const changedTools = server.tools.filter((tool) => tool.status === "changed" || tool.status === "gone").length;
                return (
                  <Row
                    key={server.id}
                    leading={
                      <Tile>
                        <Plug />
                      </Tile>
                    }
                    title={
                      <>
                        {server.name}
                        <code className="font-mono text-caption font-normal text-ink-2">{server.prefix}__…</code>
                        {!server.enabled && <Badge>{t("mcp.admin.off")}</Badge>}
                      </>
                    }
                    description={
                      <>
                        <span className="block break-all">{server.url}</span>
                        <span className="block">
                          {t(`mcp.auth.${server.auth}`)} · {t("mcp.admin.accepted", { accepted, total: server.tools.length })}
                          {changedTools > 0 && <span className="font-semibold text-danger"> · {t("mcp.admin.changedCount", { count: changedTools })}</span>}
                        </span>
                        {server.auth !== "none" && server.credential !== "valid" && <span className="block">{t("mcp.admin.connectToList")}</span>}
                        {/* A client given by hand is registered at the service with this server's own callback (ADR-0122). */}
                        {server.oauth?.client_registration === "given" && (
                          <span className="block">
                            {t("mcp.admin.callback")} <code className="font-mono break-all">{server.oauth.redirect_uri}</code>
                          </span>
                        )}
                      </>
                    }
                    below={
                      <div className="flex flex-wrap gap-2">
                        <Button size="sm" aria-label={t("mcp.admin.reviewLabel", { name: server.name })} onClick={() => setReviewing(server.id)}>
                          {t("mcp.admin.review")}
                        </Button>
                        <Button
                          size="sm"
                          busy={busy(`refresh ${server.id}`)}
                          aria-label={t("mcp.admin.refreshLabel", { name: server.name })}
                          onClick={() => void run(`refresh ${server.id}`, () => refresh(server))}
                        >
                          {busy(`refresh ${server.id}`) ? t("mcp.admin.refreshing") : t("mcp.admin.refresh")}
                        </Button>
                        <Button size="sm" busy={busy(`switch ${server.id}`)} onClick={() => void run(`switch ${server.id}`, () => switchServer(server, !server.enabled))}>
                          {server.enabled ? t("mcp.admin.switchOff") : t("mcp.admin.switchOn")}
                        </Button>
                        <Button size="sm" variant="danger" aria-label={t("mcp.admin.removeLabel", { name: server.name })} onClick={() => setRemoving(server)}>
                          {t("settings.remove")}
                        </Button>
                      </div>
                    }
                  />
                );
              })}
            </Card>
          </div>
        )}
        {/* An empty list offers it in its place. */}
        {servers.data?.length !== 0 && add}
      </div>
      {adding && <AddServerDialog onClose={() => setAdding(false)} onAdded={async () => (setAdding(false), await changed())} />}
      {current && <ReviewDialog key={current.id} server={current} onClose={() => setReviewing(null)} onSaved={changed} />}
      {removing && (
        <Dialog
          asks
          size="sm"
          onClose={() => setRemoving(null)}
          title={t("mcp.admin.removeTitle", { name: removing.name })}
          description={t("mcp.admin.removeBody")}
          footer={
            <>
              <Button onClick={() => setRemoving(null)}>{t("connection.cancel")}</Button>
              <Button variant="danger-solid" busy={busy("remove")} onClick={() => void run("remove", () => remove(removing))}>
                {t("settings.remove")}
              </Button>
            </>
          }
        />
      )}
    </Page>
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
    <Dialog
      onClose={onClose}
      title={t("mcp.admin.addTitle")}
      description={t("mcp.admin.addHint")}
      onSubmit={(event) => void add(event)}
      footer={
        <>
          <Button onClick={onClose}>{t("connection.cancel")}</Button>
          <Button type="submit" variant="primary" busy={busy}>
            {t("mcp.admin.addButton")}
          </Button>
        </>
      }
    >
      <FormField label={t("mcp.admin.name")}>{(ties) => <TextInput {...ties} name="name" required maxLength={100} />}</FormField>
      <FormField label={t("mcp.admin.prefix")} hint={t("mcp.admin.prefixHint")}>
        {(ties) => <TextInput {...ties} name="prefix" required maxLength={20} pattern="[a-z][a-z0-9]*(_[a-z0-9]+)*" autoComplete="off" mono />}
      </FormField>
      <FormField label={t("mcp.admin.address")} hint={t("mcp.admin.addressHint")}>
        {(ties) => <TextInput {...ties} name="url" type="url" required />}
      </FormField>
      <FormField label={t("mcp.admin.signIn")} hint={t(`mcp.admin.authHints.${auth}`)}>
        {(ties) => (
          <Select {...ties} value={auth} onChange={(event) => setAuth(event.target.value as McpServerAuth)}>
            {AUTHS.map((item) => (
              <option key={item} value={item}>
                {t(`mcp.auth.${item}`)}
              </option>
            ))}
          </Select>
        )}
      </FormField>
      {auth === "oauth" && (
        <>
          <FormField label={t("mcp.admin.clientId")} hint={t("mcp.admin.clientIdHint")}>
            {(ties) => <TextInput {...ties} name="oauth_client_id" autoComplete="off" />}
          </FormField>
          <FormField label={t("mcp.admin.clientSecret")}>{(ties) => <TextInput {...ties} name="oauth_client_secret" type="password" autoComplete="off" />}</FormField>
        </>
      )}
      {busy && <Notice role="status">{t("mcp.admin.connecting")}</Notice>}
      {problem && <Notice tone="error">{problem}</Notice>}
    </Dialog>
  );
}

function ToolDetails({ tool }: { tool: McpServerTool }) {
  const { t } = useTranslation();
  const listed = tool.listed;
  const accepted = tool.accepted;
  return (
    <div className="flex flex-col gap-2 text-small">
      <code className="font-mono text-caption text-ink-2">{tool.model_name}</code>
      {tool.status === "changed" && accepted && (
        <div className="rounded-md bg-hover px-3 py-2">
          <p className="font-semibold">{t("mcp.review.whenAccepted")}</p>
          <p className="whitespace-pre-wrap">{accepted.description}</p>
        </div>
      )}
      {listed ? (
        <>
          {tool.status === "changed" && <p className="font-semibold">{t("mcp.review.now")}</p>}
          <p className="whitespace-pre-wrap">{listed.description || t("mcp.review.noDescription")}</p>
          <details>
            <summary className="cursor-pointer font-semibold text-ink-2">{t("mcp.review.schema")}</summary>
            <pre className="mt-1 max-h-60 overflow-auto rounded-sm bg-hover p-2 font-mono text-caption">{JSON.stringify(listed.input_schema, null, 2)}</pre>
          </details>
          {listed.annotations && Object.keys(listed.annotations).length > 0 && (
            <p className="text-ink-2">
              {t("mcp.review.hints")} <code className="font-mono text-caption">{JSON.stringify(listed.annotations)}</code>
            </p>
          )}
        </>
      ) : (
        <p className="text-ink-2">{t("mcp.review.goneHint")}</p>
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
    <Dialog
      size="lg"
      onClose={onClose}
      title={t("mcp.review.title", { name: server.name })}
      description={t("mcp.review.hint")}
      footer={
        <>
          <Button onClick={onClose}>{t("conversationMenu.cancel")}</Button>
          <Button variant="primary" busy={busy} onClick={() => void save()}>
            {t("conversationMenu.save")}
          </Button>
        </>
      }
    >
      <Card rows>
        {server.tools.length === 0 && (
          <EmptyState icon={<Plug />} title={t("mcp.review.noTools")}>
            {t("mcp.review.noToolsHint")}
          </EmptyState>
        )}
        {server.tools.map((tool) => {
          const label = tool.listed?.title ?? tool.accepted?.title ?? tool.name;
          const usable = tool.listed !== null && tool.problem === null;
          return (
            <Row
              key={tool.name}
              leading={<Checkbox aria-label={t("mcp.review.accept", { name: label })} checked={usable && chosen.has(tool.name)} disabled={!usable} onChange={(event) => toggle(tool.name, event.target.checked)} />}
              title={
                <>
                  {label}
                  {tool.status !== "not_accepted" && <Badge tone={tool.status === "accepted" ? "ok" : "warn"}>{t(`mcp.review.status.${tool.status}`)}</Badge>}
                </>
              }
              description={tool.problem ? <span className="text-danger">{t(`mcp.review.problems.${tool.problem}`)}</span> : undefined}
              below={<ToolDetails tool={tool} />}
            />
          );
        })}
      </Card>
    </Dialog>
  );
}

// --- Each user's account (AGT-030, AGT-031) ---

/** The household's services, and the user's account on each: connect a token, sign in, or disconnect. */
export function ServicesSection() {
  const { t } = useTranslation();
  const servers = useMcpServers();
  return (
    <Page title={t("mcp.services.title")} description={t("mcp.services.hint")}>
      {servers.isPending && (
        <Card>
          <Loading />
        </Card>
      )}
      {servers.data && (
        <Card rows>
          {servers.data.length === 0 && (
            <EmptyState icon={<Plug />} title={t("mcp.services.none")}>
              {t("mcp.services.noneHint")}
            </EmptyState>
          )}
          {servers.data.map((server) => (
            <Service key={server.id} server={server} />
          ))}
        </Card>
      )}
    </Page>
  );
}

function Service({ server }: { server: McpServerSummary }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const heading = useId();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState<"connect" | "signIn" | "disconnect" | null>(null);

  async function changed() {
    await queries.invalidateQueries({ queryKey: MCP_SERVERS });
    await queries.invalidateQueries({ queryKey: HOUSEHOLD_MCP_SERVERS });
  }

  async function connect(event: React.FormEvent) {
    event.preventDefault();
    setBusy("connect");
    try {
      unwrap(await api.PUT("/mcp-servers/{server_id}/credential", { params: { path: { server_id: server.id } }, body: { token } }));
      setToken("");
      await changed();
    } catch (error) {
      notify({ kind: "error", title: t("mcp.services.notConnectedError"), text: problemText(error, t("errors.title")) });
    } finally {
      setBusy(null);
    }
  }

  async function signIn() {
    setBusy("signIn");
    try {
      const started = unwrap(await api.POST("/mcp-servers/{server_id}/sign-in", { params: { path: { server_id: server.id } } }));
      window.location.assign(started.authorization_url);
    } catch (error) {
      notify({ kind: "error", title: t("mcp.services.notConnectedError"), text: problemText(error, t("errors.title")) });
      setBusy(null);
    }
  }

  async function disconnect() {
    setBusy("disconnect");
    try {
      ok(await api.DELETE("/mcp-servers/{server_id}/credential", { params: { path: { server_id: server.id } } }));
      await changed();
    } finally {
      setBusy(null);
    }
  }

  const connected = server.credential === "valid";
  const account = !server.denied && server.auth !== "none";
  return (
    // A region named by the service, as each service was before it became a row.
    <section aria-labelledby={heading}>
      <Row
        leading={
          <Tile>
            <Plug />
          </Tile>
        }
        title={
          <>
            <span id={heading}>{server.name}</span>
            <span className="text-small font-normal text-ink-2">{server.host}</span>
          </>
        }
        description={
          <>
            {server.tools.length > 0 && <span className="block">{t("mcp.services.tools", { tools: server.tools.map((tool) => tool.title ?? tool.model_name).join(", ") })}</span>}
            {server.denied ? <span className="block">{t("permissions.lockedByAdmin")}</span> : server.auth === "none" && <span className="block">{t("mcp.services.noAccount")}</span>}
          </>
        }
        below={
          account && (
            <div className="flex flex-col gap-3">
              {server.auth === "token" && (
                <form onSubmit={(event) => void connect(event)}>
                  <FormField label={t("mcp.services.token")} hint={t("mcp.services.leastRights")}>
                    {(ties) => (
                      <div className="flex gap-2">
                        <TextInput {...ties} type="password" autoComplete="off" required value={token} onChange={(event) => setToken(event.target.value)} />
                        <Button type="submit" busy={busy === "connect"} disabled={busy !== null}>
                          {t("mcp.services.connect")}
                        </Button>
                      </div>
                    )}
                  </FormField>
                </form>
              )}
              {server.auth === "oauth" && !connected && (
                <div>
                  <Button busy={busy === "signIn"} disabled={busy !== null} onClick={() => void signIn()}>
                    {t("mcp.services.signIn")}
                  </Button>
                </div>
              )}
              {server.credential !== "missing" && (
                <div className="flex flex-col items-start gap-1">
                  <Button size="sm" busy={busy === "disconnect"} disabled={busy !== null} onClick={() => void disconnect()}>
                    {t("mcp.services.disconnect")}
                  </Button>
                  {server.auth === "oauth" && <p className="text-small text-ink-2">{t("mcp.services.revokeHint")}</p>}
                </div>
              )}
            </div>
          )
        }
      >
        {account && <Badge tone={connected ? "ok" : server.credential === "expired" ? "warn" : "neutral"}>{t(`mcp.services.state.${server.credential}`)}</Badge>}
      </Row>
    </section>
  );
}

/** Where a sign-in to a service comes back: completes it, then shows the services (ADR-0100, point 4). */
export function McpSignIn() {
  const { t } = useTranslation();
  const [search] = useSearchParams();
  // Each server has its own redirect address; the API checks the sign-in was for it (ADR-0122).
  const { serverId } = useParams();
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
        if (!state || !serverId) throw new Error("no state");
        // What the redirect carried, as it carried it, and where it came back (ADR-0100, point 5, ADR-0122).
        const body: Schemas["CompleteMcpSignInRequest"] = { server_id: serverId, state };
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
  }, [search, serverId, navigate, queries, notify, t]);

  const back = () => void navigate("/settings?section=services", { replace: true });
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* On a phone the top bar is the only way to the conversation list (UX-039). */}
      <TopBar className="md:hidden" start={<MenuButton />} />
      <div className="mx-auto w-full max-w-form p-6">
        <Page title={t("mcp.services.signingIn")}>
          {failed ? (
            <Notice tone="error" action={<Button size="sm" onClick={back}>{t("mcp.services.back")}</Button>}>
              {failed}
            </Notice>
          ) : (
            <Notice role="status">{t("mcp.services.completing")}</Notice>
          )}
        </Page>
      </div>
    </div>
  );
}

// --- Switches (AGT-029) ---

/**
 * One switch per server, with its tools: rows for the card that holds them, beside the tool switches.
 * A denied server is off and locked (ADR-0099).
 */
export function ServerSwitches({ off, onChange }: { off: string[]; onChange: (off: string[]) => void }) {
  const { t } = useTranslation();
  const servers = useMcpServers();
  if (!servers.data || servers.data.length === 0) return null;
  const isOn = (server: McpServerSummary) => !off.includes(server.id) && !server.denied;
  return (
    <>
      {servers.data.map((server) => (
        <Switch
          key={server.id}
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
      ))}
    </>
  );
}
