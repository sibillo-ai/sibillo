import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, Brain, CalendarClock, Check, ChevronRight, ListChecks, ShieldCheck, ShieldX, Sparkles, Copy, Download, FilePen, FileText, FolderOpen, Ghost, GitFork, LoaderCircle, Pencil, SlidersHorizontal, Square, Volume2 } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate, useParams } from "react-router";

import { ApiError, api, unwrap, type ModelChoice, type MessagePage, type PathRun } from "../api/client";
import type { ResumeEntry } from "../api/stream";
import { forkConversation, rewindConversation, updateConversation, useRefreshConversations } from "../conversations";
import { formatMoney, isPaid, USAGE } from "../costs";
import { MEMORY_SECTION, type MemoryChange, memoryChangeOf } from "../memory";
import { useServerTool } from "../mcp";
import { useBusy } from "../busy";
import { useNotify } from "../notices";
import { BROWSER, loadedSkillOf, savedSkillOf, SKILLS_SECTION } from "../skills";
import { durationText, folded, previewOf, tally } from "../steps";
import { ASK_USER, isPlanning, type LivePart, type LiveRun, poseOf, type RunUsage, toolActivity, useLiveRun } from "../run";
import { openTemporary } from "../temporary";
import { outcomeLabel, toolLabel } from "../tools";
import { Button, cx, Dialog, IconButton, Loading, Notice, TextArea, TopBar } from "../ui";
import { ModelSelect } from "./ModelPicker";
import { MenuButton } from "./Shell";
import { AnswerBody, AttachmentChip, AttachmentImage, Attachments, Bubble, ErrorCard, FileCard, MessageActions, SpriteLine, Step, StepDetail, Steps, ThreadCard, Turn as TurnItem, UserMessage } from "../ui/Message";
import { useVoice, type VoiceMode } from "../voice";
import { type AttachedFile, download, downloadUrl, formatSize, isImagePath, listFolder, previewUrl, useAttachments } from "../workspace";
import { ApprovalCard, scopesOf } from "./Approvals";
import { ChatSettings } from "./AssistantSettings";
import { Composer } from "./Composer";
import { InternetSwitch } from "./InternetSwitch";
import { Markdown } from "./Markdown";
import { QuestionCard, TaskList } from "./Questions";
import { Sprite } from "./Sprite";
import { type Reveal, WorkspacePanel } from "./WorkspacePanel";
import i18n from "../i18n";

type AgUiMessage = MessagePage["items"][number] & {
  content?: unknown;
  toolCalls?: { id: string; function: { name: string; arguments: string } }[];
  toolCallId?: string;
  attachments?: AttachedFile[];
  duration_ms?: number;
};

/** How near its end, in pixels, the thread still counts as at its end (UX-030). */
const END_SLACK_PX = 16;

interface Turn {
  run: PathRun;
  userText: string | null;
  attachments: AttachedFile[];
  parts: LivePart[];
}

/** The runs of the conversation, each with its user message and what answered it. */
function turnsOf(page: MessagePage): Turn[] {
  const byId = new Map(page.items.map((message) => [message.id, message as AgUiMessage]));
  // Results by call, across runs: an approved call's result comes in the run that continues it (ADR-0090).
  const results = new Map(
    page.items.filter((m) => m.role === "tool").map((m) => [(m as AgUiMessage).toolCallId, textOf((m as AgUiMessage).content)]),
  );
  // How long each call took, when the worker measured it (UX-043, ADR-0140).
  const durations = new Map(
    page.items.flatMap((m) => (m.role === "tool" && typeof (m as AgUiMessage).duration_ms === "number" ? [[(m as AgUiMessage).toolCallId, (m as AgUiMessage).duration_ms as number] as const] : [])),
  );
  return page.runs.map((run) => {
    const messages = run.message_ids.flatMap((id) => byId.get(id) ?? []);
    let userText: string | null = null;
    let attachments: AttachedFile[] = [];
    const parts: LivePart[] = [];
    for (const message of messages) {
      if (message.role === "user" && userText === null) {
        userText = textOf(message.content);
        attachments = message.attachments ?? [];
      }
      else if (message.role === "reasoning") {
        const text = textOf(message.content);
        if (text) parts.push({ kind: "reasoning", id: message.id, text });
      }
      else if (message.role === "assistant") {
        const text = textOf(message.content);
        if (text) parts.push({ kind: "text", id: message.id, text });
        for (const call of message.toolCalls ?? []) {
          const result = results.get(call.id);
          const durationMs = durations.get(call.id);
          parts.push({
            kind: "tool",
            id: call.id,
            name: call.function.name,
            args: call.function.arguments,
            ...(result === undefined ? {} : { result }),
            ...(durationMs === undefined ? {} : { durationMs }),
          });
        }
      }
    }
    return { run, userText, attachments, parts };
  });
}

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content.map((part) => (typeof part === "object" && part !== null && "text" in part ? String(part.text) : "")).join("");
  }
  return "";
}

/** The messages a person sees in a turn's answer: its texts, or one for an answer of tools only. */
function shownAnswer(turn: Turn): number {
  const texts = turn.parts.filter((part) => part.kind === "text").length;
  return texts > 0 ? texts : turn.parts.length > 0 ? 1 : 0;
}

async function allMessages(conversationId: string): Promise<MessagePage> {
  const items: MessagePage["items"] = [];
  const runs: PathRun[] = [];
  let cursor: string | undefined;
  do {
    const query = cursor === undefined ? { limit: 100 } : { limit: 100, cursor };
    const page = unwrap(
      await api.GET("/conversations/{conversation_id}/messages", { params: { path: { conversation_id: conversationId }, query } }),
    );
    items.push(...page.items);
    for (const run of page.runs) if (runs.at(-1)?.run_id !== run.run_id) runs.push(run);
    else runs[runs.length - 1] = { ...run, message_ids: [...(runs.at(-1)?.message_ids ?? []), ...run.message_ids] };
    cursor = page.next_cursor ?? undefined;
  } while (cursor !== undefined);
  return { items, runs, next_cursor: null };
}

interface PendingEdit {
  index: number;
  turn: Turn;
  text: string;
  deleted: number;
}

export function ConversationView() {
  const { t } = useTranslation();
  const { conversationId = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queries = useQueryClient();
  const refreshList = useRefreshConversations();
  const notify = useNotify();
  const actions = useBusy();
  const conversation = useQuery({
    queryKey: ["conversation", conversationId, "details"],
    queryFn: async () => unwrap(await api.GET("/conversations/{conversation_id}", { params: { path: { conversation_id: conversationId } } })),
  });
  const history = useQuery({ queryKey: ["conversation", conversationId, "messages"], queryFn: () => allMessages(conversationId) });

  // While an edited message streams, the turn it replaces and the ones after it are gone.
  const [hideFrom, setHideFrom] = useState<number | null>(null);
  const refresh = useCallback(async () => {
    await queries.invalidateQueries({ queryKey: ["conversation", conversationId] });
    await queries.invalidateQueries({ queryKey: USAGE });
    await refreshList();
  }, [queries, refreshList, conversationId]);
  const runEnded = useCallback(async () => {
    await refresh();
    setHideFrom(null);
  }, [refresh]);

  const { live, start, follow, stop, running } = useLiveRun(runEnded);
  // A hands-free turn's answer is read aloud once it is complete, and the sprite there acts out the run (UX-005).
  const voice = useVoice();
  const pose = poseOf(live);
  const showRun = voice?.showRun;
  useEffect(() => showRun?.(pose), [showRun, pose]);
  const liveStatus = live?.status;
  const liveParts = live?.parts;
  // A hands-free turn that ended asking for approval waits for the conversation's requests (UX-041).
  const [voiceAsks, setVoiceAsks] = useState(false);
  useEffect(() => {
    const said = (liveParts ?? []).flatMap((part) => (part.kind === "text" ? [part.text] : [])).join("\n\n");
    if (liveStatus === "finished" && live?.interrupted && voice?.handsFree) setVoiceAsks(true);
    else if (liveStatus === "finished") voice?.answered(said);
    else if (liveStatus === "failed") voice?.failed();
    // Only when the run ends: its parts are complete then.
  }, [liveStatus]);
  // The latest context reading stays in view after the run, until another conversation opens.
  const [contextUsage, setContextUsage] = useState<RunUsage | null>(null);
  const [usageFor, setUsageFor] = useState(conversationId);
  if (usageFor !== conversationId) {
    setUsageFor(conversationId);
    setContextUsage(null);
  }
  if (live?.usage && live.usage !== contextUsage) setContextUsage(live.usage);
  const [pending, setPending] = useState<PendingEdit | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const thread = useRef<HTMLDivElement>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [reveal, setReveal] = useState<Reveal | null>(null);
  const [panelFor, setPanelFor] = useState(conversationId);
  if (panelFor !== conversationId) {
    setPanelFor(conversationId);
    setReveal(null);
  }
  const owner = useCallback(() => Promise.resolve(conversationId), [conversationId]);
  const attachments = useAttachments(owner);
  const show = useCallback((path: string) => {
    setReveal({ path, at: Date.now() });
    setPanelOpen(true);
  }, []);

  // The first message of a new chat, handed over by the new-chat screen, with its attachments.
  const handedOver = location.state as { firstMessage?: string; attachments?: AttachedFile[]; voice?: VoiceMode; focused?: boolean } | null;
  const firstVoice = handedOver?.voice;
  const firstMessage = handedOver?.firstMessage;
  const firstAttachments = handedOver?.attachments;
  const started = useRef(false);
  useEffect(() => {
    if (firstMessage && !started.current) {
      started.current = true;
      start({ conversationId, text: firstMessage, attachments: firstAttachments ?? [], ...(firstVoice ? { voice: firstVoice } : {}) });
      void navigate(location.pathname, { replace: true, state: null });
    }
  }, [firstMessage, firstAttachments, firstVoice, conversationId, start, navigate, location.pathname]);

  // Pending approvals first, then questions; both are answered together (UX-022, ADR-0090).
  const pendingInterrupts = conversation.data?.interrupts ?? [];
  const approvals = pendingInterrupts.filter((interrupt) => interrupt.reason === "approval");
  const questions = pendingInterrupts.filter((interrupt) => interrupt.reason !== "approval");
  const pendingKey = pendingInterrupts.map((interrupt) => interrupt.id).join();
  const [decided, setDecided] = useState<{ key: string; entries: ResumeEntry[] } | null>(null);
  const decisions = decided?.key === pendingKey ? decided.entries : null;

  // In hands-free mode, each approval request is said and answered by its buttons, one after another (UX-041).
  const requested = voice?.requested;
  useEffect(() => {
    if (!voiceAsks || running || !requested || pendingInterrupts.length === 0) return;
    setVoiceAsks(false);
    if (questions.length > 0) {
      // Questions in hands-free mode are not decided yet (AGT-015): they wait on the screen, as before.
      voice?.answered("");
      return;
    }
    const ask = (index: number, entries: ResumeEntry[]) => {
      const interrupt = approvals[index];
      if (!interrupt) return;
      const decide = (entry: ResumeEntry) => {
        const all = [...entries, entry];
        if (all.length >= approvals.length) resumeWith(all, "hands_free");
        else ask(index + 1, all);
      };
      const tool = interrupt.metadata?.approval?.tool;
      requested({
        key: interrupt.id,
        sentence: interrupt.metadata?.internet_access ? t("voice.request.internet") : t("voice.request.other", { tool: tool ? toolLabel(t, tool) : "" }),
        answers: [
          { label: t("approvals.deny"), choose: () => decide({ interruptId: interrupt.id, status: "resolved", payload: { approved: false } }) },
          ...scopesOf(interrupt).map((scope) => ({
            label: t(`approvals.allow.${scope}`),
            choose: () => decide({ interruptId: interrupt.id, status: "resolved", payload: { approved: true, scope } }),
          })),
        ],
      });
    };
    ask(0, []);
  }, [voiceAsks, running, requested, pendingKey]);

  // Internet access, for the conversation or for the turn that is going on (UX-042, ADR-0115).
  const allowances = conversation.data?.allowances;
  const [wanted, setWanted] = useState<{ key: string; on: boolean } | null>(null);
  const [switching, setSwitching] = useState(false);
  // What the user chose holds until the conversation is read again.
  const stateKey = `${conversationId}:${conversation.dataUpdatedAt}`;
  const online = wanted?.key === stateKey ? wanted.on : Boolean(allowances?.internet_access || allowances?.turn_internet_access);
  // The turn's internet access shows while the turn goes on: read again once the server has started the run, and
  // recorded the answers it brings.
  const liveStarted = live?.started === true;
  useEffect(() => {
    if (liveStarted) void queries.invalidateQueries({ queryKey: ["conversation", conversationId] });
  }, [liveStarted, queries, conversationId]);
  // Answers that allow internet access turn the switch on at once: the conversation is read again only once the
  // server has recorded them (UX-042).
  function resumeWith(entries: ResumeEntry[], voice?: VoiceMode) {
    const internet = new Set(approvals.filter((interrupt) => interrupt.metadata?.internet_access).map((interrupt) => interrupt.id));
    if (entries.some((entry) => internet.has(entry.interruptId) && entry.payload && "approved" in entry.payload && entry.payload.approved)) {
      setWanted({ key: stateKey, on: true });
    }
    start({ conversationId, text: "", resume: entries, ...(voice ? { voice } : {}) });
  }
  async function switchInternet(on: boolean) {
    setWanted({ key: stateKey, on });
    const waiting = approvals.find((interrupt) => interrupt.metadata?.internet_access);
    // A request that waits, alone, is answered as "Allow in this chat".
    if (on && waiting && pendingInterrupts.length === 1 && !running) {
      start({ conversationId, text: "", resume: [{ interruptId: waiting.id, status: "resolved", payload: { approved: true, scope: "conversation" } }] });
      return;
    }
    setSwitching(true);
    try {
      await updateConversation(conversationId, { allowances: { internet_access: on, tools: allowances?.tools ?? [] } });
      await queries.invalidateQueries({ queryKey: ["conversation", conversationId] });
    } catch {
      setWanted(null);
    } finally {
      setSwitching(false);
    }
  }

  // A temporary conversation goes when its user leaves it (CNV-011).
  const temporary = conversation.data?.temporary === true;
  useEffect(() => {
    if (temporary) openTemporary(conversationId);
  }, [temporary, conversationId]);

  // A run in progress, started on another device or before a reload: follow it (CNV-015).
  const activeRunId = conversation.data?.active_run_id;
  useEffect(() => {
    if (!activeRunId || running || started.current) return;
    void api.GET("/runs/{run_id}", { params: { path: { run_id: activeRunId } } }).then((result) => {
      if (result.data?.status === "queued" || result.data?.status === "running") follow(activeRunId);
    });
  }, [activeRunId, running, follow]);

  // The thread follows the answer as it streams, but only while the user is at its end;
  // scrolled up, new text leaves it in place and a sign at its end says so (UX-030).
  const atEnd = useRef(true);
  const [behind, setBehind] = useState(false);
  const toEnd = useCallback(() => {
    const element = thread.current;
    atEnd.current = true;
    setBehind(false);
    if (element) element.scrollTop = element.scrollHeight;
  }, []);
  // Another conversation, or a run the user just started, begins at the end; a run that ends
  // leaves the thread where it is (UX-035).
  const liveRunId = live?.runId;
  useLayoutEffect(toEnd, [conversationId, toEnd]);
  useLayoutEffect(() => {
    if (liveRunId !== undefined) toEnd();
  }, [liveRunId, toEnd]);
  // Escape stops the run, as the stop button does, unless it closed a dialog or a menu (UX-034).
  useEffect(() => {
    if (!running) return;
    function key(event: KeyboardEvent) {
      if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
      if (document.querySelector("[role=dialog], [role=alertdialog], [role=menu], [role=listbox]")) return;
      void stop();
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [running, stop]);
  // A layout effect, so that the thread grows and scrolls before the browser reports a scroll.
  useLayoutEffect(() => {
    const element = thread.current;
    if (!element) return;
    if (atEnd.current) element.scrollTop = element.scrollHeight;
    else if (live) setBehind(true);
  }, [live, history.data]);
  function onThreadScroll() {
    const element = thread.current;
    if (!element) return;
    atEnd.current = element.scrollHeight - element.clientHeight - element.scrollTop <= END_SLACK_PX;
    if (atEnd.current) setBehind(false);
  }

  /** A new conversation from a copy of this one up to the turn (CNV-005). */
  async function fork(turn: Turn) {
    try {
      const copy = await forkConversation(conversationId, turn.run.run_id);
      await refreshList();
      await navigate(`/c/${copy.id}`);
    } catch (error) {
      notify({ kind: "error", title: t("errors.title"), text: t(`errors.${codeKey(error)}`) });
    }
  }

  async function chooseModel(choice: ModelChoice) {
    await updateConversation(conversationId, { model: choice });
    await refresh();
  }

  /** Editing a message rewinds to the turn before it, then sends the edited text (CNV-016, ADR-0068). */
  async function sendEdit(edit: PendingEdit) {
    setPending(null);
    setEditing(null);
    setHideFrom(edit.index);
    try {
      await rewindConversation(conversationId, edit.turn.run.parent_run_id);
      await refresh();
    } catch (error) {
      setHideFrom(null);
      notify({ kind: "error", title: t("errors.title"), text: t(`errors.${codeKey(error)}`) });
      return;
    }
    start({ conversationId, text: edit.text });
  }

  if (conversation.error instanceof ApiError && conversation.error.status === 404) {
    return <p className="p-6 text-body">{t("errors.notFound")}</p>;
  }

  const turns = history.data ? turnsOf(history.data) : [];
  const decidedCalls = new Map((history.data?.runs ?? []).flatMap((run) => run.approvals.map((item) => [item.tool_call_id, item] as const)));
  // The run being answered shows live, even when the history was loaded meanwhile (ADR-0085), until
  // the history is fetched again once it ended: a history fetched while it ran lacks its end (UX-003).
  const shown = (live !== null && hideFrom !== null ? turns.slice(0, hideFrom) : turns).filter(
    (turn) => !(live !== null && live.inHistory !== true && turn.run.run_id === live.runId),
  );
  // A failed run, once in the history, is shown there with its error (UX-014); a reason only the
  // stream gave stays with it until the next run.
  // Once the history has the live run, it shows it: never both at once (ADR-0085).
  const settled = live !== null && live.inHistory === true && shown.some((turn) => turn.run.run_id === live.runId);
  const liveReason = live?.status === "failed" ? { runId: live.runId, reason: live.reason } : null;

  function askToEdit(index: number, turn: Turn, text: string) {
    const deleted = shownAnswer(turn) + turns.slice(index + 1).reduce((sum, later) => sum + (later.userText === null ? 0 : 1) + shownAnswer(later), 0);
    const edit = { index, turn, text, deleted };
    if (deleted === 0) void sendEdit(edit);
    else setPending(edit);
  }

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
      {/* The conversation's top bar: its title, its model, its cost and its context, its files and its settings, on a
          computer and on a phone alike (UX-008, UX-039). On a computer the cost and the context are a line under the
          title; on a phone a second line of the bar holds the model, with its name, and the cost as an amount alone. */}
      <TopBar
        line
        start={<MenuButton />}
        title={conversation.data ? conversation.data.title || t("shell.untitled") : ""}
        detail={
          <div className="flex min-w-0 items-center gap-x-4 overflow-hidden text-caption whitespace-nowrap text-ink-3 tabular-nums max-md:hidden">
            <ConversationCost conversation={conversation.data} />
            {contextUsage && <ContextGauge usage={contextUsage} />}
          </div>
        }
        below={{
          className: "md:hidden",
          children: (
            <>
              {conversation.data && (
                <span className="-ms-1 flex min-w-0">
                  <ModelSelect compact value={conversation.data.model ?? null} onChange={(choice) => void chooseModel(choice)} />
                </span>
              )}
              <span className="flex-1" />
              <span className="flex flex-none items-center gap-3 text-caption text-ink-3 tabular-nums">
                <ConversationCost brief conversation={conversation.data} />
                {contextUsage && <ContextGauge brief usage={contextUsage} />}
              </span>
            </>
          ),
        }}
      >
        {conversation.data && (
          <span className="flex min-w-0 max-md:hidden">
            <ModelSelect compact value={conversation.data.model ?? null} onChange={(choice) => void chooseModel(choice)} />
          </span>
        )}
        {conversation.data && <InternetSwitch checked={online} disabled={switching} onChange={(on) => void switchInternet(on)} />}
        <Button variant="ghost" size="sm" onClick={() => setPanelOpen((open) => !open)} aria-expanded={panelOpen} aria-label={t("files.title")}>
          <FolderOpen aria-hidden="true" />
          <span className="max-md:hidden">{t("files.title")}</span>
        </Button>
        {conversation.data && (
          <IconButton label={t("assistant.chat")} onClick={() => setSettingsOpen(true)}>
            <SlidersHorizontal aria-hidden="true" />
          </IconButton>
        )}
      </TopBar>
      <div ref={thread} onScroll={onThreadScroll} className="relative min-h-0 flex-1 overflow-y-auto" aria-busy={running}>
        <ol className="mx-auto flex w-full max-w-read flex-col gap-6 px-6 pt-6 pb-8 max-md:px-4">
          {temporary && (
            <li>
              <Notice role="note" icon={<Ghost aria-hidden="true" />}>
                {t("temporary.notice")}
              </Notice>
            </li>
          )}
          {conversation.data?.task && (
            <li className="flex items-center gap-2 text-small text-ink-2">
              <CalendarClock className="size-4 flex-none" aria-hidden="true" />
              {conversation.data.task.id ? (
                <Link to={`/settings?section=tasks&task=${conversation.data.task.id}`} className="underline underline-offset-2 hover:text-ink">
                  {t("message.startedByTask", { name: conversation.data.task.name })}
                </Link>
              ) : (
                t("message.startedByDeletedTask", { name: conversation.data.task.name })
              )}
            </li>
          )}
          {conversation.data?.forked_from && (
            <li className="flex items-center gap-2 text-small text-ink-2">
              <GitFork className="size-4 flex-none" aria-hidden="true" />
              {conversation.data.forked_from.conversation_id ? (
                <Link to={`/c/${conversation.data.forked_from.conversation_id}`} className="underline underline-offset-2 hover:text-ink">
                  {t("message.forkedFrom")}
                </Link>
              ) : (
                t("message.forkedFrom")
              )}
            </li>
          )}
          {history.isPending && live === null && (
            <li>
              <Loading />
            </li>
          )}
          {shown.map((turn, index) => (
            <TurnView
              key={turn.run.run_id}
              turn={turn}
              busy={running}
              last={(live === null || settled) && index === shown.length - 1}
              stopped={settled && live.runId === turn.run.run_id && live.errorCode === "run.cancelled"}
              reason={liveReason?.runId === turn.run.run_id ? liveReason.reason : undefined}
              editing={editing === index}
              onEdit={() => setEditing(index)}
              onCancelEdit={() => setEditing(null)}
              onSendEdit={(text) => askToEdit(index, turn, text)}
              forking={actions.busy(`fork ${turn.run.run_id}`)}
              onFork={temporary ? undefined : () => void actions.run(`fork ${turn.run.run_id}`, () => fork(turn))}
              conversationId={conversationId}
              onShow={show}
              decided={decidedCalls}
            />
          ))}
          {live && !settled && (
            <TurnItem>
              {live.userText !== null && <UserBubble text={live.userText} attachments={live.attachments ?? []} onShow={show} conversationId={conversationId} />}
              <Answer parts={live.parts} conversationId={conversationId} onShow={show} running={live.status === "running"} timings={live.timings} />
              {live.status === "failed" && live.errorCode !== "run.cancelled" ? (
                <RunErrorView code={live.errorCode ?? "internal.error"} reason={live.reason ?? null} />
              ) : (
                <Activity run={live} />
              )}
            </TurnItem>
          )}
        </ol>
        {behind && (
          <div className="pointer-events-none sticky bottom-3 z-10 flex h-0 items-end justify-center">
            <div className="slide pointer-events-auto rounded-md shadow-float">
              <Button size="sm" onClick={toEnd}>
                <ArrowDown className="motion-safe:animate-bounce" aria-hidden="true" />
                {t("message.newText")}
              </Button>
            </div>
          </div>
        )}
      </div>
      {/* The message box and what waits above it, in the reading column; the canvas fades in above it. */}
      <div className="relative flex-none pt-1 pb-safe">
        <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 bottom-full h-6 bg-linear-to-b from-transparent to-canvas" />
        <div className="mx-auto w-full max-w-read px-6 max-md:px-4">
          <TaskList steps={live?.plan ?? conversation.data?.plan ?? []} />
          {/* A pending approval or question takes the message box's place until it is answered (AGT-015, UX-009, UX-022). */}
          {!running && approvals.length > 0 && decisions === null ? (
            <ApprovalCard
              key={pendingKey}
              interrupts={approvals}
              onDecided={(entries) => (questions.length > 0 ? setDecided({ key: pendingKey, entries }) : resumeWith(entries))}
            />
          ) : !running && questions.length > 0 ? (
            <QuestionCard key={questions.map((question) => question.id).join()} interrupts={questions} onAnswer={(resume) => resumeWith([...(decisions ?? []), ...resume])} />
          ) : (
            <Composer
              onSend={(text, files, voice) => start({ conversationId, text, attachments: files, ...(voice ? { voice } : {}) })}
              attachments={attachments}
              onStop={() => void stop()}
              running={running}
              model={conversation.data?.model ?? null}
              placeholder={t("composer.placeholder")}
              keepFocus={handedOver?.focused === true}
            />
          )}
        </div>
      </div>
      </div>
      <WorkspacePanel conversationId={conversationId} open={panelOpen} onOpenChange={setPanelOpen} reveal={reveal} />
      {conversation.data && <ChatSettings conversation={conversation.data} open={settingsOpen} onOpenChange={setSettingsOpen} />}
      <Dialog
        asks
        size="sm"
        open={pending !== null}
        onClose={() => setPending(null)}
        title={t("rewind.title")}
        description={t("rewind.body", { count: pending?.deleted ?? 0 })}
        footer={
          <>
            <Button onClick={() => setPending(null)}>{t("rewind.cancel")}</Button>
            <Button variant="danger-solid" onClick={() => pending && void sendEdit(pending)}>
              {t("rewind.confirm")}
            </Button>
          </>
        }
      >
        {/* Rewinding never changes the workspace, and the user is told so (UX-010). */}
        <Notice role="note" icon={<FilePen aria-hidden="true" />}>
          {t("rewind.files")}
        </Notice>
      </Dialog>
    </div>
  );
}

function codeKey(error: unknown): string {
  const code = error instanceof ApiError ? error.code : "internal.error";
  return ["model.unavailable", "model.request_failed", "model.refused", "model.egress_refused", "model.tool_misuse", "model.context_exceeded", "sandbox.unavailable", "run.worker_lost", "run.timeout", "run.step_limit"].includes(code) ? code.replace(".", "_") : "internal_error";
}

/** Why a run failed, where its answer would be, with what the model said (UX-014, MOD-015). */
function RunErrorView({ code, reason }: { code: string; reason: string | null }) {
  const { t } = useTranslation();
  return (
    <ErrorCard sprite={<Sprite pose="error" className="h-14 w-12 flex-none" />} title={t("errors.title")} reason={reason}>
      {t(`errors.${codeKey(new ApiError(0, code))}`)}
    </ErrorCard>
  );
}

/** The sprite acting out what the assistant does, and the same in words (UX-013). */
function Activity({ run }: { run: LiveRun }) {
  const { t } = useTranslation();
  const pose = poseOf(run);
  const working = run.status === "running";
  const words =
    run.status === "failed"
      ? run.errorCode === "run.cancelled"
        ? t("message.stopped")
        : t("errors.title")
      : working
        ? t(`activity.${pose}`)
        : "";
  const usage = run.usage;
  const cost = usage?.cost && isPaid([usage.cost]) ? formatMoney([usage.cost]) : null;
  return (
    <SpriteLine sprite={<Sprite pose={pose} className="h-14 w-12 flex-none" />}>
      <span role="status" className="flex items-center gap-2 text-small text-ink-2">
        <span className={working ? "live-text" : ""}>{words}</span>
        {working && cost && <span className="tabular-nums">· {cost}</span>}
      </span>
    </SpriteLine>
  );
}

/** What the conversation has cost so far (UX-008). */
function ConversationCost({ conversation, brief = false }: { conversation: { cost: Parameters<typeof formatMoney>[0] } | undefined; brief?: boolean }) {
  const { t } = useTranslation();
  if (!conversation) return null;
  // On a phone the amount alone, where the bar says whose it is (UX-039).
  if (brief)
    return (
      <span className="font-medium text-ink-2" title={t("usage.conversation")}>
        {formatMoney(conversation.cost)}
      </span>
    );
  return (
    <span className="flex flex-none items-center gap-1">
      <span>{t("usage.conversation")}</span>
      <span className="font-medium text-ink-2">{formatMoney(conversation.cost)}</span>
    </span>
  );
}

/** Tokens, shortly, in the interface language: `950`, `12.3k`, `131k` (I18N-006). */
function compact(tokens: number): string {
  const number = (value: number, digits: number) => new Intl.NumberFormat(i18n.language, { maximumFractionDigits: digits }).format(value);
  return tokens >= 1000 ? `${number(tokens / 1000, tokens >= 100_000 ? 0 : 1)}k` : number(tokens, 0);
}

/** How much of the model's context window the conversation uses: tokens, window, share and a gauge (UX-008). */
function ContextGauge({ usage, brief = false }: { usage: RunUsage; brief?: boolean }) {
  const { t } = useTranslation();
  const percent = Math.round(Math.min(1, usage.context_tokens / Math.max(1, usage.context_window)) * 100);
  const text = t("usage.contextValue", { used: compact(usage.context_tokens), size: compact(usage.context_window), percent });
  return (
    <span className="flex items-center gap-2">
      {/* On a phone the share alone; the gauge still says it in full (UX-039). */}
      <span>{brief ? `${percent}%` : text}</span>
      <span
        role="meter"
        aria-label={t("usage.context")}
        aria-valuemin={0}
        aria-valuemax={usage.context_window}
        aria-valuenow={usage.context_tokens}
        aria-valuetext={text}
        className={cx("h-1 flex-none overflow-hidden rounded-full bg-hover", brief ? "w-10" : "w-20")}
      >
        <span className={`block h-full rounded-full ${percent >= 80 ? "bg-danger" : "bg-ink-2"}`} style={{ width: `${Math.max(3, percent)}%` }} />
      </span>
    </span>
  );
}

function TurnView(props: {
  turn: Turn;
  busy: boolean;
  last: boolean;
  /** The user stopped this run here; the history does not tell a stopped run from a finished one. */
  stopped: boolean;
  // What the run's stream said about its failure, when the history keeps no reason.
  reason?: string | undefined;
  editing: boolean;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSendEdit: (text: string) => void;
  /** Absent where the conversation cannot be forked, as a temporary one (CNV-011). */
  forking: boolean;
  onFork: (() => void) | undefined;
  conversationId: string;
  onShow: (path: string) => void;
  /** How each call of the conversation that needed approval was decided, by tool call (UX-023). */
  decided: Map<string, PathRun["approvals"][number]>;
}) {
  const { t } = useTranslation();
  const { turn, busy } = props;
  const answerText = turn.parts.flatMap((part) => (part.kind === "text" ? [part.text] : [])).join("\n\n");
  return (
    <TurnItem>
      {turn.userText !== null &&
        (props.editing ? (
          <form
            className="flex w-full flex-col gap-2 self-end md:w-4/5"
            onSubmit={(event) => {
              event.preventDefault();
              const text = String(new FormData(event.currentTarget).get("text") ?? "").trim();
              if (text) props.onSendEdit(text);
            }}
          >
            <label className="sr-only" htmlFor={`edit-${turn.run.run_id}`}>
              {t("message.editLabel")}
            </label>
            <TextArea id={`edit-${turn.run.run_id}`} name="text" defaultValue={turn.userText} rows={3} autoFocus />
            <div className="flex items-center justify-end gap-2">
              <small className="flex-1 text-caption text-ink-3">{t("message.editHint")}</small>
              <Button size="sm" onClick={props.onCancelEdit}>
                {t("message.cancelEdit")}
              </Button>
              <Button type="submit" variant="primary" size="sm">
                {t("message.saveEdit")}
              </Button>
            </div>
          </form>
        ) : (
          <UserMessage
            actions={
              <MessageActions reveal="message">
                <CopyButton text={turn.userText} />
                <IconButton label={t("message.edit")} disabled={busy} onClick={props.onEdit}>
                  <Pencil aria-hidden="true" />
                </IconButton>
              </MessageActions>
            }
          >
            <UserBubble text={turn.userText} attachments={turn.attachments} onShow={props.onShow} conversationId={props.conversationId} />
          </UserMessage>
        ))}
      <Answer parts={turn.parts} conversationId={props.conversationId} onShow={props.onShow} decided={props.decided} />
      {turn.run.error && turn.run.error.code !== "run.cancelled" && (
        <RunErrorView code={turn.run.error.code} reason={turn.run.error.reason ?? props.reason ?? null} />
      )}
      {/* The last answer: the sprite waits, and says so if the user just stopped the run (CNV-003). */}
      {props.last && !turn.run.error && (
        <SpriteLine sprite={<Sprite pose="waiting" className="h-14 w-12 flex-none" />}>
          {props.stopped && (
            <span role="status" className="text-small text-ink-2">
              {t("message.stopped")}
            </span>
          )}
        </SpriteLine>
      )}
      {answerText && (
        // Each answer's cost, beside its actions and always in view; a local model's is nothing to show (UX-008).
        <MessageActions reveal="turn" shown={props.last} caption={isPaid(turn.run.cost) ? formatMoney(turn.run.cost) : undefined}>
          <CopyButton text={answerText} />
          <ReadAloudButton id={turn.run.run_id} text={answerText} />
          {props.onFork && (
            <IconButton label={t("message.fork")} busy={props.forking} disabled={busy} onClick={props.onFork}>
              <GitFork aria-hidden="true" />
            </IconButton>
          )}
        </MessageActions>
      )}
    </TurnItem>
  );
}

/** Reading an answer aloud, and stopping it, when the household has a speech model (UX-005). */
function ReadAloudButton({ id, text }: { id: string; text: string }) {
  const { t } = useTranslation();
  const voice = useVoice();
  if (!voice?.speech) return null;
  const reading = voice.reading === id;
  return (
    <IconButton
      label={reading ? t("voice.stopReading") : t("voice.readAloud")}
      disabled={voice.speechRefused}
      {...(voice.speechRefused ? { title: t("voice.refused") } : {})}
      onClick={() => (reading ? voice.stopReading() : voice.readAloud(id, text))}
    >
      {reading ? <Square fill="currentColor" aria-hidden="true" /> : <Volume2 aria-hidden="true" />}
    </IconButton>
  );
}

function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation();
  const notify = useNotify();
  return (
    <IconButton
      label={t("message.copyMessage")}
      onClick={() => {
        void navigator.clipboard.writeText(text).then(() => notify({ kind: "info", title: t("message.copied") }));
      }}
    >
      <Copy aria-hidden="true" />
    </IconButton>
  );
}

/** A message's attachments, as chips that show the file in the workspace panel (CNV-017). */
function UserBubble({
  text,
  attachments,
  onShow,
  conversationId,
}: {
  text: string;
  attachments: AttachedFile[];
  onShow: (path: string) => void;
  conversationId: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex w-full min-w-0 flex-col gap-2">
      {attachments.length > 0 && (
        <Attachments label={t("files.attachments")}>
          {attachments.map((file) => (
            <li key={file.path}>
              {/* An attached image shows as a small preview, from the workspace (UX-036). */}
              {isImagePath(file.path) ? (
                <AttachmentImage src={previewUrl(conversationId, file.path)} alt={file.path.split("/").at(-1) ?? ""} onShow={() => onShow(file.path)} />
              ) : (
                <AttachmentChip icon={<FileText aria-hidden="true" />} name={file.path.split("/").at(-1)} detail={formatSize(file.size)} onShow={() => onShow(file.path)} />
              )}
            </li>
          ))}
        </Attachments>
      )}
      <Bubble speaker={t("message.you")}>{text}</Bubble>
    </div>
  );
}

function Answer({
  parts,
  conversationId,
  onShow,
  running = false,
  decided,
  timings,
}: {
  parts: LivePart[];
  conversationId: string;
  onShow: (path: string) => void;
  running?: boolean;
  decided?: Map<string, PathRun["approvals"][number]>;
  timings?: LiveRun["timings"];
}) {
  const offers = parts.flatMap((part) => (part.kind === "tool" ? (offerOf(part) ?? []) : []));
  // Text and steps in the order they came: consecutive calls and reasoning form one block of steps (UX-003, UX-043,
  // CNV-013, ADR-0140).
  type StepPart = Extract<LivePart, { kind: "reasoning" | "tool" }>;
  type Tool = Extract<LivePart, { kind: "tool" }>;
  const blocks: (
    | { kind: "text"; part: Extract<LivePart, { kind: "text" }> }
    | { kind: "steps"; parts: StepPart[] }
    | { kind: "memory"; part: Tool; change: MemoryChange }
    | { kind: "skill"; part: Tool; name: string; saved: boolean }
  )[] = [];
  let change: MemoryChange | null;
  let skill: string | null;
  const step = (part: StepPart) => {
    const last = blocks.at(-1);
    if (last?.kind === "steps") last.parts.push(part);
    else blocks.push({ kind: "steps", parts: [part] });
  };
  for (const part of parts) {
    // A text with nothing in it yet, as a model opens before its calls, does not part the steps around it.
    if (part.kind === "text") {
      if (part.text.trim() !== "") blocks.push({ kind: "text", part });
    } else if (part.kind === "reasoning") step(part);
    else if ((change = memoryChangeOf(part.name, part.result)) !== null) {
      // What the assistant remembered, changed or forgot, where it happened (UX-027).
      blocks.push({ kind: "memory", part, change });
    } else if ((skill = loadedSkillOf(part.name, argumentsOf(part.args), part.result)) !== null) {
      // Which skill the assistant uses, and a skill it saved, where it happened (UX-028).
      blocks.push({ kind: "skill", part, name: skill, saved: false });
    } else if ((skill = savedSkillOf(part.name, part.result)) !== null) {
      blocks.push({ kind: "skill", part, name: skill, saved: true });
    } else if (offerOf(part) === null) step(part);
  }
  return (
    <AnswerBody>
      {blocks.map((block) =>
        block.kind === "text" ? (
          <Markdown key={block.part.id} text={block.part.text} />
        ) : block.kind === "memory" ? (
          <MemoryCard key={block.part.id} part={block.part} change={block.change} />
        ) : block.kind === "skill" ? (
          <SkillCard key={block.part.id} name={block.name} saved={block.saved} />
        ) : (
          <StepsBlock key={block.parts[0]?.id} parts={block.parts} running={running} decided={decided} timings={timings} />
        ),
      )}
      {offers.length > 0 && (
        <div className="flex flex-col items-start gap-2">
          {offers.map((offer) => (
            <OfferCard key={offer.id} offer={offer} conversationId={conversationId} onShow={onShow} />
          ))}
        </div>
      )}
    </AnswerBody>
  );
}

/** One block of steps, folded once the answer has ended when it is long, its last steps shown while it runs (UX-043). */
function StepsBlock({
  parts,
  running,
  decided,
  timings,
}: {
  parts: Extract<LivePart, { kind: "reasoning" | "tool" }>[];
  running: boolean;
  decided?: Map<string, PathRun["approvals"][number]> | undefined;
  timings?: LiveRun["timings"] | undefined;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const labelOf = useStepLabel();
  const lines = parts.map((part) =>
    part.kind === "reasoning" ? (
      <ReasoningView key={part.id} text={part.text} />
    ) : (
      <ToolCall
        key={part.id}
        part={part}
        running={running}
        decision={decided?.get(part.id)}
        durationMs={part.durationMs ?? timings?.[part.id]?.ms}
      />
    ),
  );
  const { hidden, shown } = folded(lines, { running, open: false });
  if (hidden === 0) return <Steps>{lines}</Steps>;
  const tallied = tally(parts.map((part) => (part.kind === "reasoning" ? t("message.reasoning") : labelOf(part))));
  const what = tallied.map(({ label, count }) => (count > 1 ? `${label} ×${count}` : label)).join(" · ");
  return (
    <Steps>
      <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)} className="group/fold min-w-0">
        <FoldLine label={running ? t("steps.earlier", { count: hidden }) : t("steps.count", { count: parts.length })} what={running ? "" : what} />
        <div className="divide-y divide-line border-t border-line">{lines.slice(0, hidden)}</div>
      </details>
      {shown}
    </Steps>
  );
}

/** The line of a folded block: how many steps, and what they were. */
function FoldLine({ label, what }: { label: string; what: string }) {
  return (
    <summary className="flex min-h-8 w-full cursor-pointer list-none items-center gap-2 px-3 py-1 text-small text-ink-2 transition-colors duration-120 hover:bg-hover focus-visible:-outline-offset-2 pointer-coarse:min-h-11 [&::-webkit-details-marker]:hidden [&>svg]:size-4 [&>svg]:flex-none">
      <ListChecks aria-hidden="true" />
      <b className="flex-none font-medium text-ink">{label}</b>
      {what && <span className="min-w-0 flex-1 basis-0 truncate text-caption">{what}</span>}
      <ChevronRight className="ms-auto text-ink-3 transition-transform duration-120 rtl:-scale-x-100 group-open/fold:rotate-90 rtl:group-open/fold:-rotate-90" aria-hidden="true" />
    </summary>
  );
}

/** A piece of the model's reasoning, a step of its block, folded where it happened (CNV-013, ADR-0085, ADR-0140). */
function ReasoningView({ text }: { text: string }) {
  const { t } = useTranslation();
  return (
    <Step icon={<Brain aria-hidden="true" />} verb={t("message.reasoning")} caption={text.replace(/\s+/g, " ").trim()} plain>
      <p className="whitespace-pre-wrap">{text}</p>
    </Step>
  );
}

/** The arguments of a call, as far as they have streamed. */
function argumentsOf(args: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(args);
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

/** Whether a call is running or done, shown and said (ADR-0085). */
function CallState({ done, running }: { done: boolean; running: boolean }) {
  const { t } = useTranslation();
  if (done) {
    return (
      <>
        <Check aria-hidden="true" />
        <span className="sr-only">{t("activity.callDone")}</span>
      </>
    );
  }
  if (!running) return null;
  return (
    <>
      <LoaderCircle className="animate-spin" aria-hidden="true" />
      <span className="sr-only">{t("activity.callRunning")}</span>
    </>
  );
}

/** The browser's tools by what they did in it (AGT-039, ADR-0140). */
const BROWSER_LABELS: Record<string, string> = {
  browser_goto: "activity.browserPage",
  browser_markdown: "activity.browserRead",
  browser_click: "activity.browserClicked",
  browser_fill: "activity.browserTyped",
};

/** What a call did, in words: its step's label (UX-003, ADR-0085, ADR-0140). */
function useStepLabel(): (part: Extract<LivePart, { kind: "tool" }>) => string {
  const { t } = useTranslation();
  return (part) => {
    const activity = toolActivity(part.name);
    const args = argumentsOf(part.args);
    const purpose = typeof args.description === "string" && args.description.trim() !== "" ? args.description.trim() : null;
    if (part.name === "load_capability" && args.id === BROWSER) return t("activity.browserOpened");
    if (part.name.startsWith("browser_")) return t(BROWSER_LABELS[part.name] ?? "activity.browserUsed");
    if (part.name === ASK_USER) return t("activity.asked");
    if (isPlanning(part.name)) return t("activity.planned");
    if (activity === "running") return purpose ? t("activity.commandFor", { purpose }) : t("activity.ran");
    if (activity === "writing") return t("activity.wrote");
    if (activity === "reading") return t("activity.read");
    if (activity === "searching") return t("activity.searched");
    return t("activity.used", { name: part.name });
  };
}

/** Tool activity as one compact line that opens to its full details, running or done (UX-003, UX-043, ADR-0140). */
function ToolCall({
  part,
  running,
  decision,
  durationMs,
}: {
  part: Extract<LivePart, { kind: "tool" }>;
  running: boolean;
  decision?: PathRun["approvals"][number] | undefined;
  durationMs?: number | undefined;
}) {
  const { t } = useTranslation();
  // A remote MCP server's tool, by its title and its server's name (UX-029).
  const serverTool = useServerTool(part.name);
  const labelOf = useStepLabel();
  const label = serverTool ? t("activity.usedOf", { name: serverTool.title, server: serverTool.server }) : labelOf(part);
  const args = argumentsOf(part.args);
  const preview = previewOf(part.name, args);
  // A call that never ran, denied or refused, is not done: its outcome says what became of it (UX-023).
  const refused = decision !== undefined && ["denied", "expired", "refused", "not_granted"].includes(decision.outcome);
  const done = part.result !== undefined && !refused;
  const outcome = decision && outcomeLabel(t, decision.outcome, decision.scope);
  return (
    <Step
      icon={<CallState done={done} running={running} />}
      verb={label}
      caption={preview}
      // How the call was decided, when it needed approval, as an icon with its words (UX-023, UX-043).
      end={
        outcome && (
          <span title={outcome} className={cx("flex flex-none items-center", refused ? "text-danger" : "text-ok")}>
            {refused ? <ShieldX className="size-4" aria-hidden="true" /> : <ShieldCheck className="size-4" aria-hidden="true" />}
            <span className="sr-only">{outcome}</span>
          </span>
        )
      }
    >
      <dl className="flex flex-col gap-1">
        <div className="flex gap-3">
          <dt className="w-28 flex-none font-semibold">{t("message.toolName")}</dt>{" "}
          <dd className="min-w-0 font-mono text-caption break-all text-ink">{part.name}</dd>{" "}
        </div>
        {durationMs !== undefined && (
          <div className="flex gap-3">
            <dt className="w-28 flex-none font-semibold">{t("message.toolDuration")}</dt>{" "}
            <dd className="tabular-nums">{durationText(durationMs)}</dd>{" "}
          </div>
        )}
        {outcome && (
          <div className="flex gap-3">
            <dt className="w-28 flex-none font-semibold">{t("message.toolDecision")}</dt>{" "}
            <dd>{outcome}</dd>{" "}
          </div>
        )}
      </dl>
      {/* Words apart when the details are copied or read as text; flex lays out no space for it. */}{" "}
      <StepDetail title={t("message.toolArguments")}>{JSON.stringify(args, null, 2) === "{}" ? part.args : JSON.stringify(args, null, 2)}</StepDetail>
      {part.result !== undefined && (
        <StepDetail title={t("message.toolResult")} tall>
          {part.result}
        </StepDetail>
      )}
    </Step>
  );
}

/** A change of the user's memory, with what it holds now and the way to the Memory page (UX-027, ADR-0095). */
function MemoryCard({ part, change }: { part: Extract<LivePart, { kind: "tool" }>; change: MemoryChange }) {
  const { t } = useTranslation();
  const args = argumentsOf(part.args);
  const label = change === "remember" ? t("memory.chatRemembered") : change === "update_memory" ? t("memory.chatChanged") : t("memory.chatForgot");
  const said = change !== "forget" && typeof args.text === "string" ? args.text : t("memory.chatForgotItem");
  return (
    <ThreadCard
      label={label}
      icon={<Brain />}
      link={
        <Link to={MEMORY_SECTION} className="flex-none text-small font-medium text-ink-2 underline underline-offset-2 hover:text-ink">
          {t("memory.chatLink")}
        </Link>
      }
    >
      {said}
    </ThreadCard>
  );
}

/** A skill the assistant loaded or saved, with the way to the Skills page (UX-028, ADR-0096). */
function SkillCard({ name, saved }: { name: string; saved: boolean }) {
  const { t } = useTranslation();
  const label = saved ? t("skills.chatSaved") : t("skills.chatUsing");
  return (
    <ThreadCard
      label={label}
      icon={<Sparkles />}
      mono
      link={
        <Link to={SKILLS_SECTION} className="flex-none text-small font-medium text-ink-2 underline underline-offset-2 hover:text-ink">
          {t("skills.chatLink")}
        </Link>
      }
    >
      {name}
    </ThreadCard>
  );
}

interface Offer {
  id: string;
  path: string;
  size: number | null;
}

/** A file the assistant offered, once the tool found it (AGT-023). */
function offerOf(part: Extract<LivePart, { kind: "tool" }>): Offer | null {
  if (part.name !== "offer_download" || part.result === undefined || !part.result.startsWith("Offered ")) return null;
  let path = "";
  try {
    path = String((JSON.parse(part.args) as { path?: unknown }).path ?? "");
  } catch {
    return null;
  }
  path = path.trim().replace(/^\/workspace/, "").replace(/^\/+|\/+$/g, "");
  const size = /\((\d+) bytes\)/.exec(part.result)?.[1];
  return path ? { id: part.id, path, size: size === undefined ? null : Number(size) } : null;
}

/** An offered file: it downloads as it is now, when the user taps it, or says it is gone (AGT-023, ADR-0079). */
function OfferCard({ offer, conversationId, onShow }: { offer: Offer; conversationId: string; onShow: (path: string) => void }) {
  const { t } = useTranslation();
  const [gone, setGone] = useState(false);
  const name = offer.path.split("/").at(-1) ?? offer.path;
  const folder = offer.path.includes("/") ? offer.path.slice(0, offer.path.lastIndexOf("/")) : "";

  async function get() {
    try {
      const entries = await listFolder(conversationId, folder);
      if (!entries.some((entry) => entry.path === offer.path && entry.type === "file")) {
        setGone(true);
        return;
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setGone(true);
        return;
      }
    }
    setGone(false);
    download(downloadUrl(conversationId, offer.path));
  }

  return (
    <FileCard
      icon={<FileText />}
      name={name}
      detail={gone ? t("files.gone") : offer.size === null ? "" : formatSize(offer.size)}
      gone={gone}
      hint={t("files.show")}
      onShow={() => onShow(offer.path)}
      action={
        <Button size="sm" onClick={() => void get()}>
          <Download aria-hidden="true" />
          {t("files.download")}
        </Button>
      }
    />
  );
}
