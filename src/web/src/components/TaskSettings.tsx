// Tasks in the app: conversations that start on their own, their triggers and grants (UX-031, TSK-001 to TSK-009,
// ADR-0106).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, ChevronLeft, MessagesSquare, Plus, ShieldAlert, Webhook } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { ApiError, api, unwrap, type Schemas } from "../api/client";
import { useMcpServers } from "../mcp";
import { useNotify } from "../notices";
import { describeSchedule } from "../schedules";
import { Badge, Button, buttonClass, Card, Checkbox, Dialog, EmptyState, FormField, Group, Notice, Page, Row, Select, Switch, TextArea, TextInput, Tile } from "../ui";

type Task = Schemas["Task"];
type TaskTrigger = Schemas["TaskTrigger"];
type TaskGrant = Schemas["TaskGrant"];
type GrantCheck = Schemas["GrantCheck"];
type TriggerInput = Schemas["TaskTriggerInput"];

export const TASKS = ["tasks"] as const;
// A name that leads to its page, in a row.
const NAME = "min-w-0 truncate underline-offset-2 hover:underline";
// What a recurrence looks like: the first Monday of the month, twice (RFC 5545).
const RECURRENCE_EXAMPLE = "RRULE:FREQ=MONTHLY;BYDAY=1MO;COUNT=2";
// The tools a task may be given for any arguments, in the order the app offers them (TSK-004).
const OPEN_GRANTS = ["web_search", "read_page", "read_file", "list_directory", "find_files", "search_files", "write_file", "edit_file", "remember"] as const;

export function useTasks() {
  return useQuery({ queryKey: TASKS, queryFn: async () => unwrap(await api.GET("/tasks")).items });
}

/** A tool or a source of the lethal trifecta in words. */
function grantLabel(t: TFunction, name: string): string {
  return t(`taskSettings.grantNames.${name}`, { defaultValue: t(`assistant.toolNames.${name}`, { defaultValue: name }) });
}

/** The user's tasks, or the page of one of them. */
export function TasksSection() {
  const [search] = useSearchParams();
  const taskId = search.get("task");
  return taskId ? <TaskPage taskId={taskId} /> : <TaskList />;
}

function TaskList() {
  const { t } = useTranslation();
  const tasks = useTasks();
  const [creating, setCreating] = useState(false);
  const [shown, setShown] = useState<string | null>(null);
  const items = tasks.data ?? [];
  return (
    <Page title={t("taskSettings.title")} description={t("taskSettings.hint")}>
      <Group
        title={t("taskSettings.list")}
        action={
          items.length !== 0 && (
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus aria-hidden="true" />
              {t("taskSettings.new")}
            </Button>
          )
        }
      >
        {tasks.data && (
          <Card>
            {items.length === 0 ? (
              <EmptyState
                icon={<CalendarClock />}
                title={t("taskSettings.none")}
                action={
                  <Button variant="primary" onClick={() => setCreating(true)}>
                    <Plus aria-hidden="true" />
                    {t("taskSettings.new")}
                  </Button>
                }
              />
            ) : (
              <ul aria-label={t("taskSettings.list")} className="divide-y divide-line">
                {items.map((task) => (
                  <TaskEntry key={task.id} task={task} onWebhook={setShown} />
                ))}
              </ul>
            )}
          </Card>
        )}
      </Group>
      {creating && <TaskDialog onClose={() => setCreating(false)} onWebhook={setShown} />}
      {shown !== null && <WebhookAddress path={shown} onClose={() => setShown(null)} />}
    </Page>
  );
}

/** When a trigger fires, in words. */
function TriggerText({ trigger }: { trigger: TaskTrigger }) {
  const { t, i18n } = useTranslation();
  if (trigger.kind === "schedule") {
    const next = trigger.next_fire_at ? new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" }).format(new Date(trigger.next_fire_at)) : null;
    return (
      <span>
        {describeSchedule(t, i18n.language, trigger.start ?? "", trigger.recurrence ?? []) ??
          t("taskSettings.asWritten", { start: trigger.start, recurrence: (trigger.recurrence ?? []).join(" ") })}
        {trigger.next_fire_at === null && ` · ${t("taskSettings.ended")}`}
        {next && ` · ${t("taskSettings.next", { when: next })}`}
      </span>
    );
  }
  if (trigger.kind === "webhook") return <span>{t("taskSettings.webhookTrigger")}</span>;
  return (
    <span>
      {t("taskSettings.eventTrigger", { event: trigger.event })}
      {trigger.problem && ` · ${t(`taskSettings.problems.${trigger.problem}`)}`}
    </span>
  );
}

function TaskEntry({ task, onWebhook }: { task: Task; onWebhook: (path: string) => void }) {
  const { t, i18n } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const [replacing, setReplacing] = useState<TaskTrigger | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [editing, setEditing] = useState(false);
  const refresh = () => queries.invalidateQueries({ queryKey: TASKS });

  async function setPaused(paused: boolean) {
    try {
      unwrap(await api.PATCH("/tasks/{task_id}", { params: { path: { task_id: task.id } }, body: { paused } }));
    } catch {
      notify({ kind: "error", title: t("assistant.notSaved") });
    }
    await refresh();
  }

  async function runNow() {
    try {
      unwrap(await api.POST("/tasks/{task_id}/fire", { params: { path: { task_id: task.id } } }));
      notify({ kind: "info", title: t("taskSettings.fired") });
    } catch (failure) {
      notify({ kind: "error", title: failure instanceof ApiError && failure.code === "task.limit_reached" ? t("taskSettings.limitReached") : t("assistant.notSaved") });
    }
    await refresh();
  }

  async function replace(trigger: TaskTrigger) {
    setReplacing(null);
    const replaced = unwrap(
      await api.POST("/tasks/{task_id}/triggers/{trigger_id}/webhook-address", { params: { path: { task_id: task.id, trigger_id: trigger.id } } }),
    );
    if (replaced.webhook_path) onWebhook(replaced.webhook_path);
    await refresh();
  }

  const skipped = task.skipped.last_at ? new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" }).format(new Date(task.skipped.last_at)) : null;
  return (
    <li>
      <Row
        title={
          <>
            <Link to={`/settings?section=tasks&task=${task.id}`} className={NAME}>
              {task.name}
            </Link>
            {task.paused && <Badge>{t("taskSettings.paused")}</Badge>}
          </>
        }
        description={task.triggers.map((trigger) => (
          <span key={trigger.id} className="flex flex-wrap items-center gap-2">
            <TriggerText trigger={trigger} />
            {trigger.kind === "webhook" && (
              <Button size="sm" onClick={() => setReplacing(trigger)}>
                {t("taskSettings.replaceAddress")}
              </Button>
            )}
          </span>
        ))}
        below={
          <>
            {task.grants.length !== 0 && (
              <p className="text-small text-ink-2">
                {t("taskSettings.grantsSummary", {
                  grants: task.grants.map((grant) => (grant.arguments ? `${grantLabel(t, grant.tool)} (${JSON.stringify(grant.arguments)})` : grantLabel(t, grant.tool))).join(", "),
                })}
              </p>
            )}
            {!task.grant_check.passes && (
              <Notice role="note" tone="warn" icon={<ShieldAlert aria-hidden="true" />}>
                {t("taskSettings.withoutGrants")}
              </Notice>
            )}
            {task.skipped.count !== 0 && skipped && <p className="text-small text-ink-2">{t("taskSettings.skipped", { count: task.skipped.count, when: skipped })}</p>}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => void runNow()} aria-label={t("taskSettings.runLabel", { name: task.name })}>
                {t("taskSettings.run")}
              </Button>
              <Button size="sm" onClick={() => setEditing(true)} aria-label={t("taskSettings.editLabel", { name: task.name })}>
                {t("taskSettings.editShort")}
              </Button>
              <Button size="sm" variant="danger" onClick={() => setDeleting(true)} aria-label={t("taskSettings.deleteLabel", { name: task.name })}>
                {t("taskSettings.delete")}
              </Button>
            </div>
          </>
        }
      >
        <label className="flex flex-none cursor-pointer items-center gap-2 text-small text-ink-2">
          {t("taskSettings.active")}
          <Switch checked={!task.paused} onChange={(on) => void setPaused(!on)} />
        </label>
      </Row>
      {editing && <TaskDialog task={task} onClose={() => setEditing(false)} onWebhook={onWebhook} />}
      {replacing && (
        <Confirm
          title={t("taskSettings.replaceTitle")}
          body={t("taskSettings.replaceBody")}
          action={t("taskSettings.replace")}
          onCancel={() => setReplacing(null)}
          onConfirm={() => void replace(replacing)}
        />
      )}
      {deleting && (
        <Confirm
          title={t("taskSettings.deleteTitle", { name: task.name })}
          body={t("taskSettings.deleteBody")}
          action={t("taskSettings.delete")}
          onCancel={() => setDeleting(false)}
          onConfirm={() => {
            setDeleting(false);
            void (async () => {
              await api.DELETE("/tasks/{task_id}", { params: { path: { task_id: task.id } } });
              await refresh();
            })();
          }}
        />
      )}
    </li>
  );
}

function Confirm(props: { title: string; body: string; action: string; onCancel: () => void; onConfirm: () => void }) {
  const { t } = useTranslation();
  return (
    <Dialog
      asks
      size="sm"
      onClose={props.onCancel}
      title={props.title}
      description={props.body}
      footer={
        <>
          <Button onClick={props.onCancel}>{t("taskSettings.cancel")}</Button>
          <Button variant="danger-solid" onClick={props.onConfirm}>
            {props.action}
          </Button>
        </>
      }
    />
  );
}

/** A webhook trigger's address, shown once, after it was made or replaced (TSK-007). */
function WebhookAddress({ path, onClose }: { path: string; onClose: () => void }) {
  const { t } = useTranslation();
  const address = `${window.location.origin}${path}`;
  return (
    <Dialog
      onClose={onClose}
      title={t("taskSettings.addressTitle")}
      description={t("taskSettings.addressBody")}
      leading={
        <Tile>
          <Webhook />
        </Tile>
      }
      footer={
        <Button variant="primary" onClick={onClose}>
          {t("taskSettings.done")}
        </Button>
      }
    >
      <p className="rounded-md bg-hover p-2 font-mono text-small break-all">{address}</p>
      <FormField label={t("taskSettings.address")}>{(ties) => <TextInput {...ties} mono readOnly value={address} onFocus={(event) => event.target.select()} />}</FormField>
    </Dialog>
  );
}

type DraftTrigger = { key: number; kind: "schedule"; start: string; recurrence: string } | { key: number; kind: "webhook" } | { key: number; kind: "mcp_event"; server_id: string; event: string; arguments: string };

/** Creating a task: its instructions, time zone, triggers and grants (UX-031). */
function TaskDialog({ task, onClose, onWebhook }: { task?: Task; onClose: () => void; onWebhook: (path: string) => void }) {
  const { t } = useTranslation();
  const grantsHint = useId();
  const queries = useQueryClient();
  const servers = useMcpServers();
  const [name, setName] = useState(task?.name ?? "");
  const [instructions, setInstructions] = useState(task?.instructions ?? "");
  const [zone, setZone] = useState(() => task?.time_zone ?? Intl.DateTimeFormat().resolvedOptions().timeZone);
  // A task's triggers as they are, which the user may remove, and the ones to add.
  const [kept, setKept] = useState<TaskTrigger[]>(task?.triggers ?? []);
  const [triggers, setTriggers] = useState<DraftTrigger[]>([]);
  const [open, setOpen] = useState<Set<string>>(() => new Set((task?.grants ?? []).filter((grant) => grant.arguments === null).map((grant) => grant.tool)));
  const [fixed, setFixed] = useState(() => {
    const exact = (task?.grants ?? []).find((grant) => grant.arguments !== null);
    return exact ? JSON.stringify({ tool: exact.tool, arguments: exact.arguments }) : "";
  });
  const [error, setError] = useState<React.ReactNode>(null);
  const [busy, setBusy] = useState(false);
  const eventTypes = (servers.data ?? []).filter((server) => !server.denied).flatMap((server) => server.event_types.map((type) => ({ server, type })));
  let next = triggers.reduce((top, item) => Math.max(top, item.key), 0);

  function trifectaText(check: GrantCheck): React.ReactNode {
    const words = (names: string[]) => names.map((item) => grantLabel(t, item)).join(", ");
    return (
      <>
        {t("taskSettings.trifecta")}{" "}
        {t("taskSettings.trifectaSources", {
          private: words(check.private_data),
          untrusted: words(check.untrusted_content),
          out: words(check.external_communication),
        })}
      </>
    );
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const grants: TaskGrant[] = [...open].map((tool) => ({ tool, arguments: null }));
      if (fixed.trim()) {
        const parsed = JSON.parse(fixed) as { tool?: string; arguments?: Record<string, unknown> };
        if (typeof parsed.tool !== "string" || typeof parsed.arguments !== "object") throw new SyntaxError("fixed");
        grants.push({ tool: parsed.tool, arguments: parsed.arguments });
      }
      const added = triggers.map((item): TriggerInput => {
        if (item.kind === "schedule") {
          const start = item.start.length === 16 ? `${item.start}:00` : item.start;
          return { kind: "schedule", start, recurrence: item.recurrence.split("\n").map((line) => line.trim()).filter((line) => line !== "") };
        }
        if (item.kind === "webhook") return { kind: "webhook" };
        return { kind: "mcp_event", server_id: item.server_id, event: item.event, arguments: JSON.parse(item.arguments || "{}") as Record<string, unknown> };
      });
      let shown: string | null = null;
      if (task === undefined) {
        const created = unwrap(await api.POST("/tasks", { body: { name, instructions, time_zone: zone, triggers: added, grants } }));
        shown = created.triggers.find((item) => item.webhook_path)?.webhook_path ?? null;
      } else {
        const path = { task_id: task.id };
        unwrap(await api.PATCH("/tasks/{task_id}", { params: { path }, body: { name, instructions, time_zone: zone, grants } }));
        // New triggers first, so that the task always keeps one (TSK-001).
        for (const trigger of added) {
          const made = unwrap(await api.POST("/tasks/{task_id}/triggers", { params: { path }, body: trigger }));
          shown = made.webhook_path ?? shown;
        }
        for (const removed of task.triggers.filter((item) => !kept.some((other) => other.id === item.id))) {
          await api.DELETE("/tasks/{task_id}/triggers/{trigger_id}", { params: { path: { ...path, trigger_id: removed.id } } });
        }
      }
      await queries.invalidateQueries({ queryKey: TASKS });
      onClose();
      if (shown) onWebhook(shown);
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === "task.lethal_trifecta" && failure.problem.grant_check) {
        setError(trifectaText(failure.problem.grant_check as GrantCheck));
      } else if (failure instanceof ApiError && failure.code === "task.grant_not_allowed") {
        setError(t("taskSettings.grantNotAllowed", { detail: failure.problem.detail ?? "" }));
      } else if (failure instanceof ApiError && failure.code === "resource.conflict") {
        setError(t("taskSettings.nameTaken"));
      } else if (failure instanceof SyntaxError) {
        setError(t("taskSettings.badJson"));
      } else {
        setError(t("taskSettings.invalid"));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      onClose={onClose}
      title={task ? t("taskSettings.edit") : t("taskSettings.new")}
      description={t("taskSettings.newHint")}
      onSubmit={(event) => void save(event)}
      footer={
        <>
          <Button onClick={onClose}>{t("taskSettings.cancel")}</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={triggers.length + kept.length === 0}>
            {t("taskSettings.save")}
          </Button>
        </>
      }
    >
      <FormField label={t("taskSettings.name")}>{(ties) => <TextInput {...ties} required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} />}</FormField>
      <FormField label={t("taskSettings.instructions")}>
        {(ties) => <TextArea {...ties} required maxLength={20000} value={instructions} onChange={(event) => setInstructions(event.target.value)} />}
      </FormField>
      <FormField label={t("taskSettings.timeZone")}>{(ties) => <TextInput {...ties} required maxLength={64} value={zone} onChange={(event) => setZone(event.target.value)} />}</FormField>
      <fieldset className="flex min-w-0 flex-col gap-2">
        <legend className="mb-2 text-small font-semibold">{t("taskSettings.triggers")}</legend>
        {kept.length + triggers.length !== 0 && (
          <Card rows>
            {kept.map((trigger) => (
              <Row key={trigger.id} title={<TriggerText trigger={trigger} />}>
                <Button size="sm" onClick={() => setKept(kept.filter((item) => item.id !== trigger.id))}>
                  {t("taskSettings.removeTrigger")}
                </Button>
              </Row>
            ))}
            {triggers.map((item) => (
              <TriggerEditor
                key={item.key}
                item={item}
                eventTypes={eventTypes.map(({ server, type }) => ({ server_id: server.id, server: server.name, event: type.name }))}
                onChange={(changed) => setTriggers(triggers.map((other) => (other.key === item.key ? changed : other)))}
                onRemove={() => setTriggers(triggers.filter((other) => other.key !== item.key))}
              />
            ))}
          </Card>
        )}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setTriggers([...triggers, { key: ++next, kind: "schedule", start: "", recurrence: "" }])}>
            {t("taskSettings.addSchedule")}
          </Button>
          <Button size="sm" onClick={() => setTriggers([...triggers, { key: ++next, kind: "webhook" }])}>
            {t("taskSettings.addWebhook")}
          </Button>
          {eventTypes.length !== 0 && (
            <Button
              size="sm"
              onClick={() => {
                const first = eventTypes[0];
                if (first) setTriggers([...triggers, { key: ++next, kind: "mcp_event", server_id: first.server.id, event: first.type.name, arguments: "{}" }]);
              }}
            >
              {t("taskSettings.addEvent")}
            </Button>
          )}
        </div>
      </fieldset>
      <fieldset aria-describedby={grantsHint} className="flex min-w-0 flex-col gap-3">
        <legend className="mb-1 text-small font-semibold">{t("taskSettings.grants")}</legend>
        <p id={grantsHint} className="text-small text-ink-2">
          {t("taskSettings.grantsHint")}
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {OPEN_GRANTS.map((tool) => (
            <label key={tool} className="flex cursor-pointer items-center gap-2 text-body">
              <Checkbox
                checked={open.has(tool)}
                onChange={(event) => {
                  const changed = new Set(open);
                  if (event.target.checked) changed.add(tool);
                  else changed.delete(tool);
                  setOpen(changed);
                }}
              />
              {grantLabel(t, tool)}
            </label>
          ))}
        </div>
        <FormField label={t("taskSettings.fixedGrant")}>
          {(ties) => <TextArea {...ties} mono value={fixed} placeholder='{"tool": "run_command", "arguments": {"command": "df -h"}}' onChange={(event) => setFixed(event.target.value)} />}
        </FormField>
      </fieldset>
      {error && <Notice tone="error">{error}</Notice>}
    </Dialog>
  );
}

function TriggerEditor(props: {
  item: DraftTrigger;
  eventTypes: { server_id: string; server: string; event: string }[];
  onChange: (item: DraftTrigger) => void;
  onRemove: () => void;
}) {
  const { t, i18n } = useTranslation();
  const { item } = props;
  const remove = (
    <Button size="sm" onClick={props.onRemove}>
      {t("taskSettings.removeTrigger")}
    </Button>
  );
  if (item.kind === "webhook") return <Row title={t("taskSettings.webhookTrigger")}>{remove}</Row>;
  if (item.kind === "schedule") {
    const lines = item.recurrence.split("\n");
    const words = item.start ? describeSchedule(t, i18n.language, item.start, lines) : null;
    return (
      <div className="flex flex-col gap-3 p-4">
        <div className="flex items-end gap-2">
          <div className="min-w-0 flex-1">
            <FormField label={t("taskSettings.starts")}>
              {(ties) => <TextInput {...ties} type="datetime-local" required value={item.start} onChange={(event) => props.onChange({ ...item, start: event.target.value })} />}
            </FormField>
          </div>
          {remove}
        </div>
        <FormField label={t("taskSettings.repeats")} hint={words ?? t("taskSettings.scheduleHint")}>
          {(ties) => <TextArea {...ties} mono value={item.recurrence} placeholder={RECURRENCE_EXAMPLE} onChange={(event) => props.onChange({ ...item, recurrence: event.target.value })} />}
        </FormField>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <FormField label={t("taskSettings.event")}>
            {(ties) => (
              <Select
                {...ties}
                value={`${item.server_id}/${item.event}`}
                onChange={(event) => {
                  const [server_id = "", ...rest] = event.target.value.split("/");
                  props.onChange({ ...item, server_id, event: rest.join("/") });
                }}
              >
                {props.eventTypes.map((type) => (
                  <option key={`${type.server_id}/${type.event}`} value={`${type.server_id}/${type.event}`}>
                    {type.server}: {type.event}
                  </option>
                ))}
              </Select>
            )}
          </FormField>
        </div>
        {remove}
      </div>
      <FormField label={t("taskSettings.eventArguments")}>
        {(ties) => <TextArea {...ties} mono value={item.arguments} onChange={(event) => props.onChange({ ...item, arguments: event.target.value })} />}
      </FormField>
    </div>
  );
}

/** A task's page: the conversations it started, newest first, with how each ended (TSK-002). */
function TaskPage({ taskId }: { taskId: string }) {
  const { t, i18n } = useTranslation();
  const task = useQuery({ queryKey: [...TASKS, taskId], queryFn: async () => unwrap(await api.GET("/tasks/{task_id}", { params: { path: { task_id: taskId } } })) });
  const started = useQuery({
    queryKey: [...TASKS, taskId, "conversations"],
    queryFn: async () => unwrap(await api.GET("/tasks/{task_id}/conversations", { params: { path: { task_id: taskId }, query: { limit: 100 } } })).items,
  });
  const format = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div>
        <Link to="/settings?section=tasks" className={buttonClass({ variant: "ghost", size: "sm" })}>
          <ChevronLeft aria-hidden="true" />
          {t("taskSettings.back")}
        </Link>
      </div>
      <Page title={task.data?.name ?? t("taskSettings.title")} description={task.data && <span className="whitespace-pre-wrap">{task.data.instructions}</span>}>
        {task.data && (
          <div className="flex flex-col gap-1 text-small text-ink-2">
            <ul className="flex flex-col gap-1">
              {task.data.triggers.map((trigger) => (
                <li key={trigger.id}>
                  <TriggerText trigger={trigger} />
                </li>
              ))}
            </ul>
            {task.data.skipped.count !== 0 && task.data.skipped.last_at && (
              <p>{t("taskSettings.skipped", { count: task.data.skipped.count, when: format.format(new Date(task.data.skipped.last_at)) })}</p>
            )}
          </div>
        )}
        <Group title={t("taskSettings.conversations")}>
          {started.data && (
            <Card>
              {started.data.length === 0 ? (
                <EmptyState icon={<MessagesSquare />} title={t("taskSettings.noConversations")} />
              ) : (
                <ul aria-label={t("taskSettings.conversations")} className="divide-y divide-line">
                  {started.data.map((item) => (
                    <li key={item.conversation_id}>
                      <Row
                        title={
                          <Link to={`/c/${item.conversation_id}`} className={NAME}>
                            {item.title || t("shell.untitled")}
                          </Link>
                        }
                        description={format.format(new Date(item.started_at))}
                      >
                        <div className="flex flex-none flex-wrap items-center justify-end gap-2">
                          <Badge>{t(`taskSettings.outcomes.${item.outcome ?? "queued"}`)}</Badge>
                          {item.without_grants && <Badge tone="warn">{t("taskSettings.ranWithoutGrants")}</Badge>}
                        </div>
                      </Row>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
        </Group>
      </Page>
    </div>
  );
}
