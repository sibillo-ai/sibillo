import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Bell, Blocks, Bot, Brain, Cable, CalendarClock, Check, ChevronLeft, Cloud, Gauge, House, KeyRound, Minus, Palette, Plug, Plus, ShieldCheck, Sparkles, TriangleAlert, UserRound, Users, X } from "lucide-react";
import { type FormEvent, Fragment, type ReactNode, useId, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useSearchParams } from "react-router";

import { ApiError, api, unwrap, type Connection, type ConnectionTest, type ModelChoice, type Schemas, type User } from "../api/client";
import { findModel, MODELS, useModels } from "../models";
import { useBusy } from "../busy";
import { useNotify } from "../notices";
import { type Theme, useTheme } from "../theme";
import { Badge, Button, Card, Checkbox, cx, Dialog, EmptyState, FormField, Group, IconButton, Loading, NamedByTopBar, NavItem, NavLabel, Notice, Page, Radio, Row, Select, TextArea, TextInput, Tile, ToggleGroup, TopBar } from "../ui";
import { AssistantSection } from "./AssistantSettings";
import { ModelSelect } from "./ModelPicker";
import { HouseholdEgressSection } from "./EgressSettings";
import { McpServersSection, ServicesSection } from "./McpSettings";
import { MemorySection } from "./MemorySettings";
import { NotificationsSection } from "./NotificationSettings";
import { PasswordSection } from "./Password";
import { MembersSection } from "./MembersSettings";
import { PasskeysSection } from "./SecuritySettings";
import { SkillsSection } from "./SkillsSettings";
import { TasksSection } from "./TaskSettings";
import { ActivitySection, ToolPermissionsSection } from "./ToolSettings";
import { UsageSection } from "./UsageSettings";
import { useOpenMenu } from "./Shell";

type SpeechSettings = Schemas["SpeechSettings"];

const CONNECTIONS = ["connections"] as const;
// The window of a connection to your own server unless set (ADR-0073).
const DEFAULT_CONTEXT_WINDOW = 8192;

type Tab = "models" | "mcp-servers" | "permissions" | "members" | "assistant" | "tasks" | "memory" | "skills" | "services" | "activity" | "usage" | "notifications" | "security" | "appearance";

// Where the sections sit beside the open one: Tailwind's `md`.
const WIDE = window.matchMedia("(min-width: 48rem)");

function watchWidth(changed: () => void) {
  WIDE.addEventListener("change", changed);
  return () => WIDE.removeEventListener("change", changed);
}

interface TabItem {
  id: Tab;
  label: string;
  icon: ReactNode;
}

/**
 * The settings: for everyone their assistant (CNV-013, CNV-014), their tasks (UX-031), their memory (UX-027), notifications on this device
 * (UX-004), their passkeys (UX-026) and the theme (UX-011), and, set apart for its admins, the household's models (UX-015, UX-016) and members.
 * One column of the form width beside the sections; on a phone the sections are a list the user enters, one page at a time (ADR-0111).
 */
export function Settings({ me }: { me: User }) {
  const { t } = useTranslation();
  const admin = me.role === "tenant_admin";
  const yours: TabItem[] = [
    { id: "assistant", label: t("assistant.title"), icon: <Bot aria-hidden="true" /> },
    { id: "tasks", label: t("settings.tasks"), icon: <CalendarClock aria-hidden="true" /> },
    { id: "memory", label: t("settings.memory"), icon: <Brain aria-hidden="true" /> },
    { id: "skills", label: t("settings.skills"), icon: <Sparkles aria-hidden="true" /> },
    { id: "services", label: t("mcp.services.title"), icon: <Cable aria-hidden="true" /> },
    { id: "activity", label: t("activity.page.title"), icon: <Activity aria-hidden="true" /> },
    { id: "usage", label: t("usage.page"), icon: <Gauge aria-hidden="true" /> },
    { id: "notifications", label: t("notifications.title"), icon: <Bell aria-hidden="true" /> },
    { id: "security", label: t("settings.security"), icon: <KeyRound aria-hidden="true" /> },
    { id: "appearance", label: t("settings.appearance"), icon: <Palette aria-hidden="true" /> },
  ];
  const household: TabItem[] = admin
    ? [
        { id: "models", label: t("settings.models"), icon: <Plug aria-hidden="true" /> },
        { id: "mcp-servers", label: t("mcp.admin.title"), icon: <Blocks aria-hidden="true" /> },
        { id: "permissions", label: t("permissions.title"), icon: <ShieldCheck aria-hidden="true" /> },
        { id: "members", label: t("settings.members"), icon: <UserRound aria-hidden="true" /> },
      ]
    : [];
  // The open section is in the address, so that a link opens it, such as the Memory page from a chat
  // (UX-027), and a reload keeps it.
  const [search, setSearch] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const openMenu = useOpenMenu();
  const entered = [...yours, ...household].find((item) => item.id === search.get("section"))?.id;
  const tab = entered ?? (admin ? "models" : "assistant");
  // On a phone no section is open until the user enters one, so none is marked as the current one.
  const beside = useSyncExternalStore(watchWidth, () => WIDE.matches);
  const shown = entered ?? (beside ? tab : null);
  // On a phone a section is a step of the history over the list of sections, so that the device's Back returns
  // to the list; beside the list, choosing a section only changes the address (UX-039).
  const from = location.state as { fromList?: boolean; fromMenu?: boolean } | null;
  const setTab = (id: Tab) => setSearch({ section: id }, beside ? { replace: true } : { state: { fromList: true } });
  /** Back, on a phone: from a section to the list of sections, and from the list to the conversation list. */
  function back() {
    if (entered) {
      if (from?.fromList) void navigate(-1);
      else setSearch({}, { replace: true });
    } else if (from?.fromMenu) void navigate(-1);
    else openMenu();
  }
  const title = [...yours, ...household].find((item) => item.id === entered)?.label ?? t("settings.title");
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* On a phone the top bar names the open page and leads back (UX-039). */}
      <TopBar
        line
        className="md:hidden"
        title={title}
        start={
          <IconButton label={entered ? t("settings.backToSettings") : t("settings.backToConversations")} onClick={back}>
            <ChevronLeft className="rtl:-scale-x-100" aria-hidden="true" />
          </IconButton>
        }
      />
      <div className="relative min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 pt-6 pb-12 md:flex-row md:justify-center md:gap-12 md:px-6 md:pt-8">
          {/* On a phone: the list of sections until one is entered, then the section alone. */}
          <nav aria-label={t("settings.sections")} className={cx("flex flex-none flex-col gap-px md:sticky md:top-8 md:w-52 md:self-start", entered && "max-md:hidden")}>
            <h1 className="sr-only">{t("settings.title")}</h1>
            <TabGroup title={t("settings.yours")} items={yours} tab={shown} onChoose={setTab} />
            {household.length > 0 && <TabGroup title={t("settings.household")} items={household} tab={shown} onChoose={setTab} />}
          </nav>
          <div className={cx("flex w-full min-w-0 max-w-form flex-col gap-8", !entered && "max-md:hidden")}>
            <NamedByTopBar value>
              {tab === "models" && admin ? (
                <ModelsSection />
              ) : tab === "mcp-servers" && admin ? (
                <McpServersSection />
              ) : tab === "permissions" && admin ? (
                <ToolPermissionsSection />
              ) : tab === "members" && admin ? (
                <MembersSection me={me} />
              ) : tab === "security" ? (
                <>
                  <PasswordSection />
                  <PasskeysSection />
                </>
              ) : tab === "notifications" ? (
                <NotificationsSection />
              ) : tab === "assistant" ? (
                <AssistantSection />
              ) : tab === "tasks" ? (
                <TasksSection />
              ) : tab === "memory" ? (
                <MemorySection />
              ) : tab === "skills" ? (
                <SkillsSection />
              ) : tab === "services" ? (
                <ServicesSection />
              ) : tab === "activity" ? (
                <ActivitySection />
              ) : tab === "usage" ? (
                <UsageSection />
              ) : (
                <AppearanceSection />
              )}
            </NamedByTopBar>
          </div>
        </div>
      </div>
    </div>
  );
}

/** The sections of one kind of settings: the user's own, or the household's (UX-015). */
function TabGroup({ title, items, tab, onChoose }: { title: string; items: TabItem[]; tab: Tab | null; onChoose: (tab: Tab) => void }) {
  const heading = useId();
  return (
    <div role="group" aria-labelledby={heading} className="flex flex-col gap-px">
      <NavLabel id={heading}>{title}</NavLabel>
      {items.map((item) => (
        <NavItem key={item.id} icon={item.icon} current={tab === item.id && "page"} onClick={() => onChoose(item.id)}>
          {item.label}
        </NavItem>
      ))}
    </div>
  );
}

function AppearanceSection() {
  const { t } = useTranslation();
  const [theme, setTheme] = useTheme();
  const themes: { value: Theme; label: string }[] = [
    { value: "system", label: t("settings.system") },
    { value: "light", label: t("settings.light") },
    { value: "dark", label: t("settings.dark") },
  ];
  return (
    <Page title={t("settings.appearance")}>
      <Card rows>
        <Row title={t("settings.theme")} description={t("settings.themeHint")}>
          <ToggleGroup label={t("settings.theme")} options={themes} value={theme} onChange={setTheme} />
        </Row>
      </Card>
    </Page>
  );
}

function ModelsSection() {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const models = useModels();
  const connections = useQuery({ queryKey: CONNECTIONS, queryFn: async () => unwrap(await api.GET("/tenant/connections")).items });
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Connection | null>(null);
  const [removing, setRemoving] = useState<Connection | null>(null);
  const [results, setResults] = useState<Record<string, ConnectionTest>>({});
  const { busy, run } = useBusy();

  async function refresh() {
    await queries.invalidateQueries({ queryKey: CONNECTIONS });
    await queries.invalidateQueries({ queryKey: MODELS });
  }

  async function chooseDefault(choice: ModelChoice) {
    unwrap(await api.PUT("/tenant/default-model", { body: choice }));
    await refresh();
    notify({ kind: "info", title: t("settings.saved") });
  }

  async function test(connection: Connection) {
    const result = unwrap(await api.POST("/tenant/connections/{connection_id}/test", { params: { path: { connection_id: connection.id } } }));
    setResults({ ...results, [connection.id]: result });
    await refresh();
  }

  async function remove(connection: Connection) {
    await api.DELETE("/tenant/connections/{connection_id}", { params: { path: { connection_id: connection.id } } });
    setRemoving(null);
    await refresh();
  }

  const current = models.data?.default;
  return (
    <Page title={t("settings.models")}>
      <Notice role="note" icon={<Users aria-hidden="true" />}>
        {t("settings.householdNote")}
      </Notice>
      <Card rows>
        <Row wide title={t("settings.defaultModel")} description={t("settings.defaultHint")}>
          <ModelSelect value={current ?? null} onChange={(choice) => void chooseDefault(choice)} label={t("settings.defaultModel")} placeholder={t("settings.noDefault")} policy="household" />
        </Row>
      </Card>
      <HouseholdEgressSection />
      <SpeechSection />
      <Group
        title={t("settings.connections")}
        description={t("settings.connectionsHint")}
        action={
          connections.data?.length !== 0 && (
            <Button size="sm" onClick={() => setAdding(true)}>
              <Plus aria-hidden="true" />
              {t("settings.add")}
            </Button>
          )
        }
      >
        <Card rows>
          {connections.isPending && <Loading />}
          {connections.data?.length === 0 && (
            <EmptyState
              icon={<Plug />}
              title={t("settings.noConnections")}
              action={
                <Button variant="primary" onClick={() => setAdding(true)}>
                  <Plus aria-hidden="true" />
                  {t("settings.add")}
                </Button>
              }
            >
              {t("settings.noConnectionsHint")}
            </EmptyState>
          )}
          {connections.data?.map((connection) => (
            <Row
              key={connection.id}
              leading={<Tile>{connection.location === "local" ? <House /> : <Cloud />}</Tile>}
              title={
                <>
                  {connection.name}
                  <Badge>{connection.location === "local" ? t("settings.local") : t("settings.remote")}</Badge>
                </>
              }
              description={<span className="font-mono break-all">{connection.base_url}</span>}
              below={
                <>
                  <ServedWindows connection={connection} models={models.data?.items ?? []} />
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" busy={busy(`test ${connection.id}`)} onClick={() => void run(`test ${connection.id}`, () => test(connection))}>
                      {t("settings.test")}
                    </Button>
                    <Button size="sm" aria-label={t("settings.editLabel", { name: connection.name })} onClick={() => setEditing(connection)}>
                      {t("settings.edit")}
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => setRemoving(connection)}>
                      {t("settings.remove")}
                    </Button>
                  </div>
                  {connection.id in results && <TestResult test={results[connection.id] as ConnectionTest} />}
                </>
              }
            >
              <Badge tone="ok">
                <Check aria-hidden="true" />
                {t("settings.modelCount", { count: connection.model_count })}
              </Badge>
            </Row>
          ))}
        </Card>
      </Group>
      {adding && <ConnectionDialog onClose={() => setAdding(false)} onSaved={refresh} existing={connections.data ?? []} />}
      {editing && <ConnectionDialog key={editing.id} connection={editing} onClose={() => setEditing(null)} onSaved={refresh} existing={connections.data ?? []} />}
      {removing && (
        <Dialog
          asks
          size="sm"
          onClose={() => setRemoving(null)}
          title={t("settings.removeTitle", { name: removing.name })}
          description={t("settings.removeBody")}
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

/** Models an Ollama server runs with a smaller window than their connection's, and how to raise it (MOD-019, ADR-0093). */
function ServedWindows({ connection, models }: { connection: Connection; models: Schemas["ModelOption"][] }) {
  const { t, i18n } = useTranslation();
  const configured = connection.context_window;
  const smaller = models.filter(
    (model) => model.connection_id === connection.id && configured !== null && model.served_context_window !== null && model.served_context_window < configured,
  );
  if (configured === null || smaller.length === 0) return null;
  const number = (value: number) => value.toLocaleString(i18n.language);
  return (
    <Notice role="note" tone="warn" icon={<TriangleAlert aria-hidden="true" />}>
      <ul className="flex flex-col gap-1">
        {smaller.map((model) => (
          <li key={model.model}>{t("settings.servedWindow", { model: model.name, served: number(model.served_context_window ?? 0), configured: number(configured) })}</li>
        ))}
      </ul>
      <p className="mt-1 text-ink-2">{t("settings.servedWindowFix", { configured: number(configured) })}</p>
    </Notice>
  );
}

/** The household's speech models: one that transcribes spoken turns, one that reads aloud with a voice (API-006, ADR-0088). */
function SpeechSection() {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const models = useModels();
  const current = models.data?.speech ?? { transcription: null, speech: null };
  const speechModel = findModel(models.data?.items, current.speech);
  const [pending, setPending] = useState<{ choice: ModelChoice; voice: string } | null>(null);
  const shown = pending ?? (current.speech ? { choice: current.speech, voice: current.speech.voice } : null);
  const shownModel = findModel(models.data?.items, shown?.choice) ?? speechModel;
  const voiceField = useId();

  async function save(settings: SpeechSettings) {
    try {
      unwrap(await api.PUT("/tenant/speech", { body: settings }));
      await queries.invalidateQueries({ queryKey: MODELS });
      setPending(null);
      notify({ kind: "info", title: t("settings.saved") });
    } catch {
      notify({ kind: "error", title: t("errors.title"), text: t("errors.internal_error") });
    }
  }

  function chooseSpeech(choice: ModelChoice) {
    const voices = findModel(models.data?.items, choice)?.voices ?? [];
    const voice = voices[0];
    if (voice) void save({ ...current, speech: { ...choice, voice } });
    else setPending({ choice, voice: "" });
  }

  return (
    <Group title={t("settings.voice")} description={t("settings.voiceHint")}>
      <Card rows>
        <Row wide title={t("settings.transcriptionModel")}>
          <ModelSelect kind="transcription" value={current.transcription} onChange={(choice) => void save({ ...current, transcription: choice })} label={t("settings.transcriptionModel")} placeholder={t("settings.noTranscription")} />
          {current.transcription && (
            <Button size="sm" onClick={() => void save({ ...current, transcription: null })}>
              {t("settings.remove")}
            </Button>
          )}
        </Row>
        <Row wide title={t("settings.speechModel")}>
          <ModelSelect kind="speech" value={shown?.choice ?? null} onChange={chooseSpeech} label={t("settings.speechModel")} placeholder={t("settings.noSpeech")} />
          {current.speech && (
            <Button size="sm" onClick={() => void save({ ...current, speech: null })}>
              {t("settings.remove")}
            </Button>
          )}
        </Row>
        {shown && (
          <Row wide title={t("settings.voiceName")} htmlFor={voiceField}>
            <form
              className="flex min-w-0 flex-1 items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                const voice = String(new FormData(event.currentTarget).get("voice") ?? "").trim();
                if (voice) void save({ ...current, speech: { ...shown.choice, voice } });
              }}
            >
              {shownModel?.voices?.length ? (
                <Select
                  id={voiceField}
                  name="voice"
                  defaultValue={shown.voice}
                  key={`${shown.choice.model}-${shown.voice}`}
                  onChange={(event) => void save({ ...current, speech: { ...shown.choice, voice: event.target.value } })}
                >
                  {shownModel.voices.map((voice) => (
                    <option key={voice}>{voice}</option>
                  ))}
                </Select>
              ) : (
                <>
                  <TextInput id={voiceField} name="voice" defaultValue={shown.voice} key={`${shown.choice.model}-${shown.voice}`} required maxLength={200} placeholder={t("settings.voicePlaceholder")} />
                  <Button type="submit" size="sm">
                    {t("settings.saveVoice")}
                  </Button>
                </>
              )}
            </form>
          </Row>
        )}
      </Card>
    </Group>
  );
}

/** A connection test, step by step, with the reason for a failure and how to fix it (UX-016). */
function TestResult({ test }: { test: ConnectionTest }) {
  const { t } = useTranslation();
  const reason = test.reason;
  return (
    <div role={test.passed ? "status" : "alert"} className={cx("flex flex-col gap-3 rounded-md px-4 py-3 text-small", test.passed ? "bg-ok-soft" : "bg-danger-soft")}>
      <div className={cx("flex items-center gap-2 text-body font-semibold", test.passed ? "text-ok" : "text-danger")}>
        {test.passed ? <Check className="size-4" aria-hidden="true" /> : <X className="size-4" aria-hidden="true" />}
        {test.passed ? t("connection.passed") : t(`connection.reasons.${reason ?? "http_error"}`)}
      </div>
      <p>
        {test.passed
          ? t("connection.passedBody", { count: test.model_count ?? 0 })
          : t(`connection.fixes.${reason ?? "http_error"}`)}
      </p>
      <ol className="flex flex-col gap-2">
        {test.steps.map((step) => (
          <li key={step.step} className={cx("flex items-start gap-2", step.outcome === "skipped" && "text-ink-3")}>
            <span className={cx("mt-px flex-none", step.outcome === "passed" ? "text-ok" : step.outcome === "failed" ? "text-danger" : "")} aria-hidden="true">
              {step.outcome === "passed" ? <Check className="size-4" /> : step.outcome === "failed" ? <X className="size-4" /> : <Minus className="size-4" />}
            </span>
            <span className="min-w-0 flex-1">
              <span className={step.outcome === "skipped" ? "font-medium" : "font-semibold"}>{t(`connection.steps.${step.step}`)}</span>
              <span className={cx("block font-mono text-caption break-all", step.outcome === "failed" ? "text-danger" : "text-ink-2")}>{step.detail}</span>
            </span>
            <span className="flex-none text-caption text-ink-3 tabular-nums">{step.duration_ms === null ? "" : step.duration_ms >= 1000 ? `${Math.round(step.duration_ms / 1000)} s` : `${step.duration_ms} ms`}</span>
          </li>
        ))}
      </ol>
      {test.technical_detail && (
        <details>
          <summary className="cursor-pointer font-semibold text-ink-2">{t("connection.technical")}</summary>
          <pre className="mt-2 rounded-sm bg-hover p-2 font-mono text-caption break-all whitespace-pre-wrap">{test.technical_detail}</pre>
        </details>
      )}
    </div>
  );
}

/** Adds a connection, or changes one (UX-016, UX-025); a change that fails its test is not saved (MOD-013). */
function ConnectionDialog(props: { onClose: () => void; onSaved: () => Promise<void>; existing: Connection[]; connection?: Connection }) {
  const { t } = useTranslation();
  const notify = useNotify();
  const editing = props.connection;
  const [chosenKind, setKind] = useState<"openrouter" | "openai">("openrouter");
  const kind = editing?.kind ?? chosenKind;
  const [result, setResult] = useState<ConnectionTest | null>(null);
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  // A stored key goes only to the address it was given for: a new address asks for it again (UX-025, ADR-0117).
  const [moved, setMoved] = useState(false);
  const [removingKey, setRemovingKey] = useState(false);
  const keyAgain = Boolean(editing?.has_api_key) && moved && !removingKey;

  /** OpenRouter needs only its key; its name is OpenRouter, numbered when the household has one already. */
  function request(form: HTMLFormElement) {
    const data = new FormData(form);
    const field = (name: string) => String(data.get(name) ?? "").trim();
    if (kind === "openrouter") {
      const taken = new Set(props.existing.map((connection) => connection.name));
      let name = t("connection.openrouter");
      for (let number = 2; taken.has(name); number += 1) name = `${t("connection.openrouter")} ${number}`;
      return { name, kind, api_key: field("api_key") };
    }
    const key = field("api_key");
    const window = field("context_window");
    const seeing = named(field("image_models"));
    return {
      name: field("name"),
      kind,
      base_url: field("base_url"),
      location: field("location") === "remote" ? ("remote" as const) : ("local" as const),
      ...(window ? { context_window: Number(window) } : {}),
      ...(seeing.length > 0 ? { image_models: seeing } : {}),
      ...(key ? { api_key: key } : {}),
    };
  }

  /** Only what the admin changed; an empty key keeps the current one. */
  function changes(form: HTMLFormElement, connection: Connection): Schemas["UpdateConnectionRequest"] {
    const data = new FormData(form);
    const field = (name: string) => String(data.get(name) ?? "").trim();
    const update: Schemas["UpdateConnectionRequest"] = {};
    if (field("name") !== connection.name) update.name = field("name");
    const key = field("api_key");
    if (data.get("remove_key") === "on") update.api_key = null;
    else if (key) update.api_key = key;
    if (connection.kind === "openai") {
      if (field("base_url") !== connection.base_url) update.base_url = field("base_url");
      const location = field("location") === "remote" ? "remote" : "local";
      if (location !== connection.location) update.location = location;
      const window = Number(field("context_window"));
      if (field("context_window") && window !== connection.context_window) update.context_window = window;
      // A recognized server says which of its models see images, and the field is not shown (MOD-020).
      const seeing = named(field("image_models"));
      if (data.has("image_models") && seeing.join("\n") !== connection.image_models.join("\n")) update.image_models = seeing;
    }
    return update;
  }

  async function save(event: FormEvent<HTMLFormElement>, connection: Connection) {
    event.preventDefault();
    const update = changes(event.currentTarget, connection);
    if (Object.keys(update).length === 0) {
      props.onClose();
      return;
    }
    setBusy("save");
    setResult(null);
    try {
      const saved = unwrap(await api.PATCH("/tenant/connections/{connection_id}", { params: { path: { connection_id: connection.id } }, body: update }));
      await props.onSaved();
      props.onClose();
      notify({ kind: "info", title: t("connection.saved", { name: saved.name }) });
    } catch (error) {
      failed(error);
    } finally {
      setBusy(null);
    }
  }

  function failed(error: unknown) {
    // A connection that fails its test is not saved; its test says why (MOD-013).
    const test = error instanceof ApiError ? (error.problem.test as ConnectionTest | undefined) : undefined;
    if (test) setResult(test);
    else if (error instanceof ApiError && error.problem.title) notify({ kind: "error", title: t("errors.title"), text: String(error.problem.detail ?? error.problem.title) });
    else notify({ kind: "error", title: t("errors.title"), text: t("errors.internal_error") });
  }

  async function runTest(form: HTMLFormElement | null) {
    if (form === null || !form.reportValidity()) return;
    setBusy("test");
    setResult(null);
    try {
      setResult(unwrap(await api.POST("/tenant/connection-tests", { body: request(form) })));
    } finally {
      setBusy(null);
    }
  }

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("save");
    setResult(null);
    const body = request(event.currentTarget);
    try {
      const connection = unwrap(await api.POST("/tenant/connections", { body }));
      await props.onSaved();
      props.onClose();
      notify({
        kind: "info",
        title: t("connection.connected", { name: connection.name }),
        text: t("connection.connectedBody", { count: connection.model_count }),
      });
    } catch (error) {
      failed(error);
    } finally {
      setBusy(null);
    }
  }

  const kinds = [
    { value: "openrouter" as const, label: t("connection.openrouter") },
    { value: "openai" as const, label: t("connection.server") },
  ];
  return (
    <Dialog
      onClose={props.onClose}
      title={editing ? t("connection.editTitle", { name: editing.name }) : t("connection.title")}
      description={editing ? t("connection.editDescription") : t("connection.kind")}
      descriptionHidden
      onSubmit={(event) => void (editing ? save(event, editing) : connect(event))}
      footerStart={
        !editing && (
          <Button busy={busy === "test"} disabled={busy !== null} onClick={(event) => void runTest(event.currentTarget.form)}>
            {t("connection.test")}
          </Button>
        )
      }
      footer={
        <>
          <Button onClick={props.onClose}>{t("connection.cancel")}</Button>
          <Button type="submit" variant="primary" busy={busy === "save"} disabled={busy !== null}>
            {editing ? t("connection.save") : t("connection.connect")}
          </Button>
        </>
      }
    >
      {!editing && (
        <div>
          <ToggleGroup label={t("connection.kind")} options={kinds} value={kind} onChange={(next) => (setKind(next), setResult(null))} />
        </div>
      )}
      {/* Keyed by the kind, so that changing it empties the fields. */}
      <Fragment key={kind}>
        {kind === "openrouter" ? (
          <>
            {editing && <FormField label={t("connection.name")}>{(ties) => <TextInput {...ties} name="name" required maxLength={100} defaultValue={editing.name} />}</FormField>}
            <FormField label={editing ? t("connection.newApiKey") : t("connection.apiKey")} hint={editing ? t("connection.keepKeyHint") : t("connection.apiKeyHint")}>
              {(ties) => <TextInput {...ties} name="api_key" type="password" autoComplete="off" required={!editing} />}
            </FormField>
          </>
        ) : (
          <>
            <FormField label={t("connection.name")}>{(ties) => <TextInput {...ties} name="name" required maxLength={100} defaultValue={editing?.name} />}</FormField>
            <FormField label={t("connection.address")} hint={t("connection.addressHint")}>
              {(ties) => (
                <TextInput
                  {...ties}
                  name="base_url"
                  type="url"
                  required
                  defaultValue={editing?.base_url}
                  onChange={(event) => setMoved(editing !== undefined && event.currentTarget.value.trim().replace(/\/+$/, "") !== editing.base_url)}
                />
              )}
            </FormField>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-2 text-small font-semibold">{t("connection.where")}</legend>
              <label className="flex items-center gap-2 text-body">
                <Radio name="location" value="local" defaultChecked={(editing?.location ?? "local") === "local"} />
                {t("connection.atHome")}
              </label>
              <label className="flex items-center gap-2 text-body">
                <Radio name="location" value="remote" defaultChecked={editing?.location === "remote"} />
                {t("connection.elsewhere")}
              </label>
            </fieldset>
            <FormField label={t("connection.contextWindow")} hint={t("connection.contextWindowHint")}>
              {(ties) => <TextInput {...ties} name="context_window" type="number" min={512} max={10000000} step={1} required defaultValue={editing?.context_window ?? DEFAULT_CONTEXT_WINDOW} />}
            </FormField>
            {!editing?.server && (
              <FormField label={t("connection.imageModels")} hint={t("connection.imageModelsHint")}>
                {(ties) => <TextArea {...ties} name="image_models" rows={2} defaultValue={editing?.image_models.join("\n") ?? ""} />}
              </FormField>
            )}
            <FormField label={editing ? t("connection.newApiKeyOptional") : t("connection.apiKeyOptional")} hint={keyAgain ? t("connection.newAddressKeyHint") : editing?.has_api_key ? t("connection.keepKeyHint") : undefined}>
              {(ties) => <TextInput {...ties} name="api_key" type="password" autoComplete="off" required={keyAgain} />}
            </FormField>
            {editing?.has_api_key && (
              <label className="flex items-center gap-2 text-body">
                <Checkbox name="remove_key" onChange={(event) => setRemovingKey(event.currentTarget.checked)} />
                {t("connection.removeKey")}
              </label>
            )}
          </>
        )}
      </Fragment>
      {busy && (
        <p role="status" className="live-text text-body">
          {t("connection.testing")}
        </p>
      )}
      {result && <TestResult test={result} />}
    </Dialog>
  );
}

/** The model names of a field, one per line, without repeats (MOD-020). */
function named(value: string): string[] {
  return [...new Set(value.split("\n").map((name) => name.trim()).filter(Boolean))];
}
