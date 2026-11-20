// Tasks in the app: conversations that start on their own, their triggers and grants (UX-031, TSK-001 to TSK-009,
// ADR-0106).
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, ShieldAlert, Webhook } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { ApiError, api, unwrap, type Schemas } from "../api/client";
import { useMcpServers } from "../mcp";
import { useNotify } from "../notices";
import { describeSchedule } from "../schedules";
import { Switch } from "./AssistantSettings";

type Task = Schemas["Task"];
type TaskTrigger = Schemas["TaskTrigger"];
type TaskGrant = Schemas["TaskGrant"];
type GrantCheck = Schemas["GrantCheck"];
type TriggerInput = Schemas["TaskTriggerInput"];

export const TASKS = ["tasks"] as const;
const BUTTON = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-hover disabled:opacity-50";
const SMALL = "inline-flex h-8 items-center justify-center rounded-[10px] border border-line-strong bg-surface px-3 text-[13px] font-semibold hover:bg-hover disabled:opacity-50";
const PRIMARY = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg disabled:opacity-50";
const DANGER = "h-[38px] rounded-[10px] bg-danger px-4 text-sm font-semibold text-on-danger disabled:opacity-50";
const INPUT = "h-10 w-full rounded-[10px] border border-line-strong bg-bg px-3 outline-none focus:border-accent";
const TEXTAREA = "min-h-24 w-full rounded-[10px] border border-line-strong bg-bg px-3 py-2 text-sm outline-none focus:border-accent";
const DIALOG = "slide fixed top-1/2 left-1/2 z-50 max-h-[90dvh] w-[min(94vw,34rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[20px] bg-raised p-[22px] shadow-soft";
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
  const heading = useId();
  const tasks = useTasks();
  const [creating, setCreating] = useState(false);
  const [shown, setShown] = useState<string | null>(null);
  const items = tasks.data ?? [];
  return (
    <section aria-labelledby={heading} className="flex flex-col gap-3.5">
      <div>
        <h2 id={heading} className="mb-1 text-base font-bold">
          {t("taskSettings.title")}
        </h2>
        <p className="max-w-[62ch] text-sm text-muted">{t("taskSettings.hint")}</p>
      </div>
      {tasks.data && items.length === 0 && <p className="text-sm text-muted">{t("taskSettings.none")}</p>}
      <ul aria-label={t("taskSettings.list")} className="flex flex-col gap-2">
        {items.map((task) => (
          <TaskEntry key={task.id} task={task} onWebhook={setShown} />
        ))}
      </ul>
      <div>
        <button type="button" className={BUTTON} onClick={() => setCreating(true)}>
          <CalendarClock className="size-[18px]" aria-hidden="true" />
          {t("taskSettings.new")}
        </button>
      </div>
      {creating && <TaskDialog onClose={() => setCreating(false)} onWebhook={setShown} />}
      {shown !== null && <WebhookAddress path={shown} onClose={() => setShown(null)} />}
    </section>
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
    <li className="flex flex-col gap-2 rounded-2xl border border-line bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Link to={`/settings?section=tasks&task=${task.id}`} className="min-w-0 flex-1 truncate font-semibold underline-offset-2 hover:underline">
          {task.name}
        </Link>
        {task.paused && <span className="rounded-full bg-hover px-2 py-0.5 text-xs font-semibold text-muted">{t("taskSettings.paused")}</span>}
      </div>
      <div className="flex flex-col gap-0.5 text-[13px] text-muted">
        {task.triggers.map((trigger) => (
          <p key={trigger.id} className="flex flex-wrap items-center gap-2">
            <TriggerText trigger={trigger} />
            {trigger.kind === "webhook" && (
              <button type="button" className={SMALL} onClick={() => setReplacing(trigger)}>
                {t("taskSettings.replaceAddress")}
              </button>
            )}
          </p>
        ))}
      </div>
      {task.grants.length !== 0 && (
        <p className="text-[13px] text-muted">
          {t("taskSettings.grantsSummary", {
            grants: task.grants.map((grant) => (grant.arguments ? `${grantLabel(t, grant.tool)} (${JSON.stringify(grant.arguments)})` : grantLabel(t, grant.tool))).join(", "),
          })}
        </p>
      )}
      {!task.grant_check.passes && (
        <p className="flex items-start gap-1.5 text-[13px] text-danger">
          <ShieldAlert className="mt-px size-4 flex-none" aria-hidden="true" />
          {t("taskSettings.withoutGrants")}
        </p>
      )}
      {task.skipped.count !== 0 && skipped && <p className="text-[13px] text-muted">{t("taskSettings.skipped", { count: task.skipped.count, when: skipped })}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <Switch label={t("taskSettings.active")} checked={!task.paused} onChange={(on) => void setPaused(!on)} />
        <button type="button" className={SMALL} onClick={() => void runNow()} aria-label={t("taskSettings.runLabel", { name: task.name })}>
          {t("taskSettings.run")}
        </button>
        <button type="button" className={SMALL} onClick={() => setEditing(true)} aria-label={t("taskSettings.editLabel", { name: task.name })}>
          {t("taskSettings.editShort")}
        </button>
        <button type="button" className={SMALL} onClick={() => setDeleting(true)} aria-label={t("taskSettings.deleteLabel", { name: task.name })}>
          {t("taskSettings.delete")}
        </button>
      </div>
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
    <Dialog.Root open onOpenChange={(open) => !open && props.onCancel()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content role="alertdialog" className={DIALOG}>
          <Dialog.Title className="mb-2 text-lg font-bold">{props.title}</Dialog.Title>
          <Dialog.Description className="text-sm text-muted">{props.body}</Dialog.Description>
          <div className="mt-[18px] flex flex-wrap justify-end gap-2">
            <Dialog.Close className={BUTTON}>{t("taskSettings.cancel")}</Dialog.Close>
            <button type="button" className={DANGER} onClick={props.onConfirm}>
              {props.action}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** A webhook trigger's address, shown once, after it was made or replaced (TSK-007). */
function WebhookAddress({ path, onClose }: { path: string; onClose: () => void }) {
  const { t } = useTranslation();
  const field = useId();
  const address = `${window.location.origin}${path}`;
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className={DIALOG}>
          <Dialog.Title className="mb-2 flex items-center gap-2 text-lg font-bold">
            <Webhook className="size-5 text-accent" aria-hidden="true" />
            {t("taskSettings.addressTitle")}
          </Dialog.Title>
          <Dialog.Description className="text-sm text-muted">{t("taskSettings.addressBody")}</Dialog.Description>
          <p className="mt-3 rounded-lg bg-hover p-2 font-mono text-[12.5px] break-all">{address}</p>
          <label htmlFor={field} className="mt-3.5 flex flex-col gap-1.5">
            <span className="text-[13.5px] font-semibold">{t("taskSettings.address")}</span>
            <input id={field} readOnly value={address} className={`${INPUT} font-mono text-[13px]`} onFocus={(event) => event.target.select()} />
          </label>
          <div className="mt-[18px] flex justify-end">
            <Dialog.Close className={PRIMARY}>{t("taskSettings.done")}</Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

type DraftTrigger = { key: number; kind: "schedule"; start: string; recurrence: string } | { key: number; kind: "webhook" } | { key: number; kind: "mcp_event"; server_id: string; event: string; arguments: string };

/** Creating a task: its instructions, time zone, triggers and grants (UX-031). */
function TaskDialog({ task, onClose, onWebhook }: { task?: Task; onClose: () => void; onWebhook: (path: string) => void }) {
  const { t } = useTranslation();
  const ids = { name: useId(), instructions: useId(), zone: useId(), fixed: useId() };
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
    <Dialog.Root open onOpenChange={(value) => !value && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className={DIALOG}>
          <Dialog.Title className="mb-2 text-lg font-bold">{task ? t("taskSettings.edit") : t("taskSettings.new")}</Dialog.Title>
          <Dialog.Description className="text-sm text-muted">{t("taskSettings.newHint")}</Dialog.Description>
          <form onSubmit={(event) => void save(event)} className="mt-3.5 flex flex-col gap-3.5">
            <label htmlFor={ids.name} className="flex flex-col gap-1.5">
              <span className="text-[13.5px] font-semibold">{t("taskSettings.name")}</span>
              <input id={ids.name} required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} className={INPUT} />
            </label>
            <label htmlFor={ids.instructions} className="flex flex-col gap-1.5">
              <span className="text-[13.5px] font-semibold">{t("taskSettings.instructions")}</span>
              <textarea id={ids.instructions} required maxLength={20000} value={instructions} onChange={(event) => setInstructions(event.target.value)} className={TEXTAREA} />
            </label>
            <label htmlFor={ids.zone} className="flex flex-col gap-1.5">
              <span className="text-[13.5px] font-semibold">{t("taskSettings.timeZone")}</span>
              <input id={ids.zone} required maxLength={64} value={zone} onChange={(event) => setZone(event.target.value)} className={INPUT} />
            </label>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-[13.5px] font-semibold">{t("taskSettings.triggers")}</legend>
              {kept.map((trigger) => (
                <div key={trigger.id} className="flex items-center justify-between gap-2 rounded-xl border border-line px-3 py-2 text-sm">
                  <TriggerText trigger={trigger} />
                  <button type="button" className={SMALL} onClick={() => setKept(kept.filter((item) => item.id !== trigger.id))}>
                    {t("taskSettings.removeTrigger")}
                  </button>
                </div>
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
              <div className="flex flex-wrap gap-2">
                <button type="button" className={SMALL} onClick={() => setTriggers([...triggers, { key: ++next, kind: "schedule", start: "", recurrence: "" }])}>
                  {t("taskSettings.addSchedule")}
                </button>
                <button type="button" className={SMALL} onClick={() => setTriggers([...triggers, { key: ++next, kind: "webhook" }])}>
                  {t("taskSettings.addWebhook")}
                </button>
                {eventTypes.length !== 0 && (
                  <button
                    type="button"
                    className={SMALL}
                    onClick={() => {
                      const first = eventTypes[0];
                      if (first) setTriggers([...triggers, { key: ++next, kind: "mcp_event", server_id: first.server.id, event: first.type.name, arguments: "{}" }]);
                    }}
                  >
                    {t("taskSettings.addEvent")}
                  </button>
                )}
              </div>
            </fieldset>
            <fieldset aria-describedby={`${ids.fixed}-hint`} className="flex flex-col gap-1">
              <legend className="mb-1 text-[13.5px] font-semibold">{t("taskSettings.grants")}</legend>
              <p id={`${ids.fixed}-hint`} className="mb-1 text-[12.5px] text-muted">
                {t("taskSettings.grantsHint")}
              </p>
              <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
                {OPEN_GRANTS.map((tool) => (
                  <label key={tool} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
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
              <label htmlFor={ids.fixed} className="mt-2 flex flex-col gap-1.5">
                <span className="text-[13px] font-semibold">{t("taskSettings.fixedGrant")}</span>
                <textarea id={ids.fixed} value={fixed} placeholder='{"tool": "run_command", "arguments": {"command": "df -h"}}' onChange={(event) => setFixed(event.target.value)} className={`${TEXTAREA} min-h-16 font-mono`} />
              </label>
            </fieldset>
            {error && (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Dialog.Close className={BUTTON}>{t("taskSettings.cancel")}</Dialog.Close>
              <button type="submit" className={PRIMARY} disabled={busy || triggers.length + kept.length === 0}>
                {t("taskSettings.save")}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function TriggerEditor(props: {
  item: DraftTrigger;
  eventTypes: { server_id: string; server: string; event: string }[];
  onChange: (item: DraftTrigger) => void;
  onRemove: () => void;
}) {
  const { t, i18n } = useTranslation();
  const field = useId();
  const repeats = useId();
  const { item } = props;
  const remove = (
    <button type="button" className={SMALL} onClick={props.onRemove}>
      {t("taskSettings.removeTrigger")}
    </button>
  );
  if (item.kind === "webhook") {
    return (
      <div className="flex items-center justify-between gap-2 rounded-xl border border-line px-3 py-2 text-sm">
        <span>{t("taskSettings.webhookTrigger")}</span>
        {remove}
      </div>
    );
  }
  if (item.kind === "schedule") {
    const lines = item.recurrence.split("\n");
    const words = item.start ? describeSchedule(t, i18n.language, item.start, lines) : null;
    return (
      <div className="flex flex-col gap-1.5 rounded-xl border border-line px-3 py-2">
        <div className="flex items-end gap-2">
          <label htmlFor={field} className="flex flex-1 flex-col gap-1 text-[13px] font-semibold">
            {t("taskSettings.starts")}
            <input id={field} type="datetime-local" required value={item.start} onChange={(event) => props.onChange({ ...item, start: event.target.value })} className={INPUT} />
          </label>
          {remove}
        </div>
        <label htmlFor={repeats} className="flex flex-col gap-1 text-[13px] font-semibold">
          {t("taskSettings.repeats")}
          <textarea
            id={repeats}
            value={item.recurrence}
            placeholder={RECURRENCE_EXAMPLE}
            onChange={(event) => props.onChange({ ...item, recurrence: event.target.value })}
            className={`${TEXTAREA} min-h-12 font-mono`}
          />
        </label>
        <p className="text-[12.5px] text-muted">{words ?? t("taskSettings.scheduleHint")}</p>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-line px-3 py-2">
      <label htmlFor={field} className="text-[13px] font-semibold">
        {t("taskSettings.event")}
      </label>
      <div className="flex items-center gap-2">
        <select
          id={field}
          value={`${item.server_id}/${item.event}`}
          onChange={(event) => {
            const [server_id = "", ...rest] = event.target.value.split("/");
            props.onChange({ ...item, server_id, event: rest.join("/") });
          }}
          className={INPUT}
        >
          {props.eventTypes.map((type) => (
            <option key={`${type.server_id}/${type.event}`} value={`${type.server_id}/${type.event}`}>
              {type.server}: {type.event}
            </option>
          ))}
        </select>
        {remove}
      </div>
      <label className="flex flex-col gap-1 text-[12.5px] text-muted">
        {t("taskSettings.eventArguments")}
        <textarea value={item.arguments} onChange={(event) => props.onChange({ ...item, arguments: event.target.value })} className={`${TEXTAREA} min-h-12 font-mono`} />
      </label>
    </div>
  );
}

/** A task's page: the conversations it started, newest first, with how each ended (TSK-002). */
function TaskPage({ taskId }: { taskId: string }) {
  const { t, i18n } = useTranslation();
  const heading = useId();
  const task = useQuery({ queryKey: [...TASKS, taskId], queryFn: async () => unwrap(await api.GET("/tasks/{task_id}", { params: { path: { task_id: taskId } } })) });
  const started = useQuery({
    queryKey: [...TASKS, taskId, "conversations"],
    queryFn: async () => unwrap(await api.GET("/tasks/{task_id}/conversations", { params: { path: { task_id: taskId }, query: { limit: 100 } } })).items,
  });
  const format = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  return (
    <section aria-labelledby={heading} className="flex flex-col gap-3.5">
      <Link to="/settings?section=tasks" className="text-sm text-muted underline underline-offset-2 hover:text-fg">
        {t("taskSettings.back")}
      </Link>
      <div>
        <h2 id={heading} className="mb-1 text-base font-bold">
          {task.data?.name ?? t("taskSettings.title")}
        </h2>
        {task.data && <p className="max-w-[62ch] text-sm whitespace-pre-wrap text-muted">{task.data.instructions}</p>}
      </div>
      {task.data && (
        <ul className="flex flex-col gap-0.5 text-[13px] text-muted">
          {task.data.triggers.map((trigger) => (
            <li key={trigger.id}>
              <TriggerText trigger={trigger} />
            </li>
          ))}
        </ul>
      )}
      {task.data && task.data.skipped.count !== 0 && task.data.skipped.last_at && (
        <p className="text-[13px] text-muted">{t("taskSettings.skipped", { count: task.data.skipped.count, when: format.format(new Date(task.data.skipped.last_at)) })}</p>
      )}
      {started.data && started.data.length === 0 && <p className="text-sm text-muted">{t("taskSettings.noConversations")}</p>}
      <ul aria-label={t("taskSettings.conversations")} className="flex flex-col gap-2">
        {(started.data ?? []).map((item) => (
          <li key={item.conversation_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl border border-line bg-surface px-4 py-3">
            <Link to={`/c/${item.conversation_id}`} className="min-w-0 flex-1 truncate font-semibold underline-offset-2 hover:underline">
              {item.title || t("shell.untitled")}
            </Link>
            <span className="text-[13px] text-muted">{format.format(new Date(item.started_at))}</span>
            <span className="rounded-full bg-hover px-2 py-0.5 text-xs font-semibold text-muted">{t(`taskSettings.outcomes.${item.outcome ?? "queued"}`)}</span>
            {item.without_grants && <span className="text-xs font-semibold text-danger">{t("taskSettings.ranWithoutGrants")}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
