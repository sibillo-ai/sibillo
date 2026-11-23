import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Folder as FolderIcon, FolderPlus, MessageSquare, SquarePen } from "lucide-react";
import { createContext, type DragEvent, type FormEvent, useContext, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { api, unwrap, type Conversation, type Folder, type ListEntry } from "../api/client";
import { useBusy } from "../busy";
import { useRunning } from "../changes";
import { CONVERSATIONS, createFolder, updateConversation, updateFolder, useConversationList } from "../conversations";
import { Badge, Button, buttonClass, cx, Dialog, EmptyState, FormField, IconButton, Loading, NavItem, NavLabel, SearchInput, TextInput } from "../ui";
import { DROP_TARGET, NavEntry } from "../ui/Sidebar";
import { ConversationMenu } from "./ConversationMenu";

type Move = Pick<Conversation, "folder_id" | "pinned">;

/** The conversation being dragged, and how to move it where it is dropped (CNV-019). */
const Dragging = createContext<{ dragged: Conversation | null; start: (conversation: Conversation | null) => void; drop: (move: Partial<Move>) => void }>({
  dragged: null,
  start: () => undefined,
  drop: () => undefined,
});

/** What a place where a conversation can be dropped needs: it shows that it takes it, and moves it. */
function useDropTarget(move: Partial<Move>) {
  const { dragged, drop } = useContext(Dragging);
  const [over, setOver] = useState(false);
  if (dragged === null) return { over: false, props: {} };
  return {
    over,
    props: {
      onDragOver: (event: DragEvent) => {
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect = "move";
        setOver(true);
      },
      onDragLeave: (event: DragEvent) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(false);
      },
      onDrop: (event: DragEvent) => {
        event.preventDefault();
        event.stopPropagation();
        setOver(false);
        drop(move);
      },
    },
  };
}

/** Folders and conversations, pinned first, then newest; a search over them all (CNV-007 to CNV-009). */
export function ConversationList() {
  const { t } = useTranslation();
  const list = useConversationList();
  const queries = useQueryClient();
  const [query, setQuery] = useState("");
  const [dragged, setDragged] = useState<Conversation | null>(null);

  // Dropped on the top, pinned; on the others, unpinned; on a folder, into it (CNV-019).
  async function drop(move: Partial<Move>) {
    const conversation = dragged;
    setDragged(null);
    if (conversation === null) return;
    const changes = Object.fromEntries(Object.entries(move).filter(([key, value]) => conversation[key as keyof Move] !== value));
    if (Object.keys(changes).length === 0) return;
    await updateConversation(conversation.id, changes);
    await queries.invalidateQueries({ queryKey: CONVERSATIONS });
  }
  const entries = list.data ?? [];
  const folders = entries.flatMap((entry) => (entry.kind === "folder" ? [entry.folder] : []));
  const isPinned = (entry: ListEntry) => (entry.kind === "folder" ? entry.folder.pinned : entry.conversation.pinned);
  const pinned = entries.filter(isPinned);
  const others = entries.filter((entry) => !isPinned(entry));

  return (
    <>
      <div className="flex flex-none items-center gap-1">
        <div className="min-w-0 flex-1">
          <SearchInput label={t("shell.search")} placeholder={t("shell.searchPlaceholder")} value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        {/* The new chat, beside the search and as tall as it (ADR-0111). */}
        <Link to="/" aria-label={t("shell.newChat")} title={t("shell.newChat")} className={buttonClass({ size: "sm", square: true })}>
          <SquarePen aria-hidden="true" />
        </Link>
      </div>
      {/* Wider than the sidebar's padding by a step, so that the outline of a focused entry is not cut. */}
      <div className="-mx-1 flex min-h-0 flex-1 flex-col overflow-y-auto px-1">
        {query.trim() ? (
          <SearchResults query={query.trim()} />
        ) : (
          <Dragging.Provider value={{ dragged, start: setDragged, drop: (move) => void drop(move) }}>
            {list.isPending && <Loading compact />}
            {entries.length === 0 && list.isSuccess && (
              <EmptyState icon={<MessageSquare aria-hidden="true" />} title={t("shell.empty")}>
                {t("shell.emptyHint")}
              </EmptyState>
            )}
            {pinned.length > 0 && <Group title={t("shell.pinned")} entries={pinned} folders={folders} move={{ pinned: true, folder_id: null }} />}
            {pinned.length === 0 && dragged !== null && <PinHere />}
            {others.length > 0 && <Group title={pinned.length > 0 ? t("shell.recent") : null} entries={others} folders={folders} move={{ pinned: false, folder_id: null }} />}
          </Dragging.Provider>
        )}
      </div>
    </>
  );
}

/** The top of the list while nothing is pinned: a conversation dropped there is pinned (CNV-019). */
function PinHere() {
  const { t } = useTranslation();
  const target = useDropTarget({ pinned: true, folder_id: null });
  return (
    <div {...target.props} className={cx("flex-none rounded-sm border border-dashed border-line-strong p-2 text-center text-small text-ink-2", target.over && DROP_TARGET)}>
      {t("shell.dropToPin")}
    </div>
  );
}

function Group({ title, entries, folders, move }: { title: string | null; entries: ListEntry[]; folders: Folder[]; move: Partial<Move> }) {
  const heading = useId();
  const target = useDropTarget(move);
  return (
    <section aria-labelledby={title ? heading : undefined} {...target.props} className={cx("flex-none rounded-sm", target.over && DROP_TARGET)}>
      {title && <NavLabel id={heading}>{title}</NavLabel>}
      <ul className="flex flex-col gap-px">
        {entries.map((entry) =>
          entry.kind === "folder" ? (
            <FolderItem key={entry.folder.id} folder={entry.folder} conversations={entry.conversations} folders={folders} />
          ) : (
            <ConversationItem key={entry.conversation.id} conversation={entry.conversation} folders={folders} />
          ),
        )}
      </ul>
    </section>
  );
}

function ConversationItem({ conversation, folders }: { conversation: Conversation; folders: Folder[] }) {
  const { t } = useTranslation();
  const running = useRunning();
  const { dragged, start } = useContext(Dragging);
  return (
    <NavEntry
      to={`/c/${conversation.id}`}
      title={conversation.title || t("shell.untitled")}
      // A conversation a task started says which (UX-031).
      detail={conversation.task ? t("shell.byTask", { name: conversation.task.name }) : undefined}
      end={running.has(conversation.id) ? <Badge tone="accent">{t("shell.running")}</Badge> : undefined}
      menu={<ConversationMenu conversation={conversation} folders={folders} />}
      dimmed={dragged?.id === conversation.id}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        start(conversation);
      }}
      onDragEnd={() => start(null)}
    />
  );
}

/** A folder: it collapses and expands, and remembers which on every device (CNV-008). */
function FolderItem({ folder, conversations, folders }: { folder: Folder; conversations: Conversation[]; folders: Folder[] }) {
  const queries = useQueryClient();
  const target = useDropTarget({ folder_id: folder.id });
  const expanded = !folder.collapsed;
  async function toggle() {
    await updateFolder(folder.id, { collapsed: expanded });
    await queries.invalidateQueries({ queryKey: CONVERSATIONS });
  }
  return (
    <li {...target.props} className={cx("rounded-sm", target.over && DROP_TARGET)}>
      <NavItem
        onClick={() => void toggle()}
        aria-expanded={expanded}
        icon={
          <>
            <ChevronRight className={cx("transition-transform duration-120 rtl:-scale-x-100", expanded && "rotate-90 rtl:-rotate-90")} aria-hidden="true" />
            <FolderIcon aria-hidden="true" />
          </>
        }
        end={conversations.length > 0 ? conversations.length : undefined}
      >
        {folder.name}
      </NavItem>
      {expanded && (
        <ul aria-label={folder.name} className="mt-px flex flex-col gap-px ps-6">
          {conversations.map((conversation) => (
            <ConversationItem key={conversation.id} conversation={conversation} folders={folders} />
          ))}
        </ul>
      )}
    </li>
  );
}

function SearchResults({ query }: { query: string }) {
  const { t } = useTranslation();
  const results = useQuery({
    queryKey: ["search", query],
    queryFn: async () => unwrap(await api.GET("/search", { params: { query: { q: query } } })).items,
  });
  if (results.isPending) return <Loading compact />;
  if (results.data?.length === 0) return <p className="p-2 text-small text-ink-2">{t("shell.noResults")}</p>;
  return (
    <ul aria-label={t("shell.results")} className="flex flex-col gap-px">
      {results.data?.map((result) => (
        <NavEntry key={result.conversation_id} to={`/c/${result.conversation_id}`} title={result.title || t("shell.untitled")} detail={result.snippet} detailLines={2} />
      ))}
    </ul>
  );
}

/** The button that makes a new folder, with the dialog that names it (CNV-007); beside the name of the app (ADR-0111). */
export function NewFolderButton() {
  const { t } = useTranslation();
  const [naming, setNaming] = useState(false);
  return (
    <>
      <IconButton label={t("shell.newFolder")} onClick={() => setNaming(true)}>
        <FolderPlus aria-hidden="true" />
      </IconButton>
      <NewFolder open={naming} onClose={() => setNaming(false)} />
    </>
  );
}

function NewFolder({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const { busy, run } = useBusy();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("name") ?? "").trim();
    if (!name) return;
    await run("create", async () => {
      await createFolder(name);
      await queries.invalidateQueries({ queryKey: CONVERSATIONS });
      onClose();
    });
  }
  return (
    <Dialog
      open={open}
      size="sm"
      onClose={onClose}
      title={t("shell.newFolder")}
      description={t("shell.folderName")}
      descriptionHidden
      onSubmit={(event) => void submit(event)}
      footer={
        <>
          <Button onClick={onClose}>{t("conversationMenu.cancel")}</Button>
          <Button type="submit" variant="primary" busy={busy("create")}>
            {t("shell.createFolder")}
          </Button>
        </>
      }
    >
      <FormField label={t("shell.folderName")}>{(ties) => <TextInput {...ties} name="name" required maxLength={100} autoFocus />}</FormField>
    </Dialog>
  );
}
