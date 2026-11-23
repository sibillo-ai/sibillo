import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, File, Folder, FolderPlus, Link2, Maximize2, Pencil, RotateCcw, Trash2, Upload, X } from "lucide-react";
import { type CSSProperties, type FormEvent, type KeyboardEvent, useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { useBusy } from "../busy";
import { useNotify } from "../notices";
import { Button, Checkbox, Dialog, FileInput, FormField, IconButton, Loading, TextInput } from "../ui";
import { CodeFrame, Meter, PanelHeader, PanelSheet, TreeEntry, Viewer } from "../ui/Panel";
import {
  archiveUrl,
  createFolder,
  deleteEntry,
  download,
  downloadUrl,
  formatSize,
  languageOf,
  listFolder,
  moveEntry,
  pageUrl,
  previewKind,
  previewUrl,
  resetWorkspace,
  upload,
  type WorkspaceEntry,
  workspaceSummary,
} from "../workspace";
import { errorKey } from "./Composer";
import { CodeBlock, Markdown } from "./Markdown";
import { ResizeHandle, usePanelWidth } from "./ResizeHandle";

const WIDE = "(min-width: 768px)";
// The API shows at most this much of a text (UX-020).
const TEXT_PREVIEW_BYTES = 1024 * 1024;
const CSV_ROWS = 200;
// Beside the conversation, the panel takes at most half of the window.
const PANEL_LIMIT = { "--panel-limit": "50vw" } as CSSProperties;
// In the panel, a preview is at most this tall; the full view of a diagram fits the window.
const PREVIEW_LIMIT = { "--preview-limit": "60vh" } as CSSProperties;
const DIAGRAM_LIMIT = { "--preview-limit": "calc(100dvh - 10rem)" } as CSSProperties;
const NOTE = "text-small text-ink-2";

/** Whether the screen is wide enough for the panel beside the conversation. */
export function useWide(): boolean {
  return useSyncExternalStore(
    (changed) => {
      const query = window.matchMedia(WIDE);
      query.addEventListener("change", changed);
      return () => query.removeEventListener("change", changed);
    },
    () => window.matchMedia(WIDE).matches,
  );
}

export function workspaceKey(conversationId: string): unknown[] {
  return ["conversation", conversationId, "workspace"];
}

function parentOf(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash === -1 ? "" : path.slice(0, slash);
}

function useFolder(conversationId: string, path: string, enabled = true) {
  return useQuery({
    queryKey: [...workspaceKey(conversationId), "folder", path],
    queryFn: () => listFolder(conversationId, path),
    enabled,
  });
}

/** A file to show in the panel, as a chip or a card asks (UX-019). */
export interface Reveal {
  path: string;
  at: number;
}

/**
 * The conversation's workspace: a tree with previews and the actions on its files, beside the
 * conversation on a computer and a full-screen sheet on a phone (UX-019, ADR-0079).
 */
export function WorkspacePanel(props: { conversationId: string; open: boolean; onOpenChange: (open: boolean) => void; reveal: Reveal | null }) {
  const { t } = useTranslation();
  const wide = useWide();
  const title = useId();
  const panel = usePanelWidth("sibillo.filesWidth", 400, 300, 760);
  const close = () => props.onOpenChange(false);
  if (wide) {
    if (!props.open) return null;
    return (
      <section aria-labelledby={title} style={{ width: panel.width, ...PANEL_LIMIT }} className="relative flex max-w-(--panel-limit) flex-none flex-col border-l border-line bg-canvas">
        <ResizeHandle label={t("files.resize")} side="left" panel={panel} />
        <PanelBody conversationId={props.conversationId} reveal={props.reveal} titleId={title} onClose={close} />
      </section>
    );
  }
  return (
    <PanelSheet open={props.open} onOpenChange={props.onOpenChange}>
      <PanelBody conversationId={props.conversationId} reveal={props.reveal} onClose={close} />
    </PanelSheet>
  );
}

type Asking = { kind: "delete" | "rename"; entry: WorkspaceEntry } | { kind: "folder"; in: string } | { kind: "reset" };

interface Transfer {
  key: string;
  name: string;
  progress: number;
}

/** The panel's header and what is under it. With a `titleId` it is beside the conversation; without, it is in the sheet its title names. */
function PanelBody({ conversationId, reveal, titleId, onClose }: { conversationId: string; reveal: Reveal | null; titleId?: string; onClose: () => void }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const [hidden, setHidden] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [asking, setAsking] = useState<Asking | null>(null);
  const actions = useBusy();
  const [large, setLarge] = useState<WorkspaceEntry | null>(null);
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const picker = useRef<HTMLInputElement>(null);
  const summary = useQuery({ queryKey: [...workspaceKey(conversationId), "summary"], queryFn: () => workspaceSummary(conversationId) });

  // A chip or a card opened the panel on one of its files: show it.
  const [revealed, setRevealed] = useState<Reveal | null>(null);
  if (reveal !== null && reveal !== revealed) {
    setRevealed(reveal);
    const folders = new Set(expanded);
    let folder = parentOf(reveal.path);
    while (folder) {
      folders.add(folder);
      folder = parentOf(folder);
    }
    setExpanded(folders);
    setSelected(reveal.path);
  }

  const siblings = useFolder(conversationId, selected === null ? "" : parentOf(selected), selected !== null);
  const entry = selected === null ? null : (siblings.data?.find((candidate) => candidate.path === selected) ?? null);
  // Uploads and new folders go into the chosen folder, or the chosen file's folder.
  const target = entry === null ? "" : entry.type === "folder" ? entry.path : parentOf(entry.path);

  async function changed() {
    await queries.invalidateQueries({ queryKey: workspaceKey(conversationId) });
  }

  function failed(error: unknown) {
    const code = error instanceof ApiError ? error.code : "internal.error";
    notify({ kind: "error", title: t("errors.title"), text: t(`files.errors.${errorKey(code)}`) });
  }

  function toggle(path: string) {
    setExpanded((all) => {
      const next = new Set(all);
      if (!next.delete(path)) next.add(path);
      return next;
    });
  }

  function uploadHere(files: File[]) {
    for (const file of files) {
      const key = crypto.randomUUID();
      setTransfers((all) => [...all, { key, name: file.name, progress: 0 }]);
      const path = target ? `${target}/${file.name}` : file.name;
      const transfer = upload(conversationId, file, (progress) => setTransfers((all) => all.map((item) => (item.key === key ? { ...item, progress } : item))), path);
      transfer.done
        .then(async () => {
          if (target) setExpanded((all) => new Set(all).add(target));
          await changed();
        }, failed)
        .finally(() => setTransfers((all) => all.filter((item) => item.key !== key)));
    }
  }

  // The dialog that asked stays open, its button busy, until the action is done (UX-038).
  async function run(action: () => Promise<unknown>, after?: () => void) {
    await actions.run("asked", async () => {
      try {
        await action();
        after?.();
      } catch (error) {
        failed(error);
      }
      setAsking(null);
      await changed();
    });
  }

  const quota = summary.data;
  return (
    <>
      <PanelHeader title={t("files.title")} titleId={titleId} sheet={titleId === undefined}>
        <IconButton label={t("files.upload")} onClick={() => picker.current?.click()}>
          <Upload aria-hidden="true" />
        </IconButton>
        <FileInput
          ref={picker}
          multiple
          aria-label={t("files.upload")}
          onChange={(event) => {
            if (event.target.files) uploadHere([...event.target.files]);
            event.target.value = "";
          }}
        />
        <IconButton label={t("files.newFolder")} onClick={() => setAsking({ kind: "folder", in: target })}>
          <FolderPlus aria-hidden="true" />
        </IconButton>
        <IconButton label={t("files.reset")} onClick={() => setAsking({ kind: "reset" })}>
          <RotateCcw aria-hidden="true" />
        </IconButton>
        <IconButton label={t("files.close")} onClick={onClose}>
          <X aria-hidden="true" />
        </IconButton>
      </PanelHeader>
      <div className="flex min-h-0 flex-1 flex-col">
        {transfers.length > 0 && (
          <ul aria-label={t("files.uploads")} className={`flex-none border-b border-line px-4 py-2 ${NOTE}`}>
            {transfers.map((item) => (
              <li key={item.key} className="truncate">
                {t("files.uploadingName", { name: item.name, percent: Math.round(item.progress * 100) })}
              </li>
            ))}
          </ul>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="flex justify-end px-4 pt-2">
            <label className={`flex cursor-pointer items-center gap-2 ${NOTE}`}>
              <Checkbox checked={hidden} onChange={(event) => setHidden(event.target.checked)} />
              {t("files.showHidden")}
            </label>
          </div>
          <Tree conversationId={conversationId} hidden={hidden} expanded={expanded} selected={selected} onToggle={toggle} onSelect={setSelected} />
          {entry !== null && (
            <section aria-label={t("files.preview")} className="px-2 pb-2">
              <CodeFrame
                title={
                  <div className="py-1">
                    <p className="truncate text-small font-semibold text-ink">{entry.name}</p>
                    <p className="truncate font-normal tabular-nums">
                      {entry.type === "file" ? `${formatSize(entry.size)} · ` : ""}
                      {new Date(entry.modified).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
                    </p>
                  </div>
                }
                actions={
                  <>
                    {(entry.type === "file" || entry.type === "folder") && (
                      <IconButton label={t("files.download")} onClick={() => download(entry.type === "folder" ? archiveUrl(conversationId, entry.path) : downloadUrl(conversationId, entry.path))}>
                        <Download aria-hidden="true" />
                      </IconButton>
                    )}
                    <IconButton label={t("files.rename")} onClick={() => setAsking({ kind: "rename", entry })}>
                      <Pencil aria-hidden="true" />
                    </IconButton>
                    <IconButton label={t("files.delete")} onClick={() => setAsking({ kind: "delete", entry })}>
                      <Trash2 aria-hidden="true" />
                    </IconButton>
                    {entry.type === "file" && previewKind(entry.name) !== "none" && (
                      <IconButton label={t("files.fullView")} onClick={() => setLarge(entry)}>
                        <Maximize2 aria-hidden="true" />
                      </IconButton>
                    )}
                  </>
                }
              >
                {/* Each file opens as its preview, not as the last file's source. */}
                {entry.type === "file" ? (
                  <div className="p-3">
                    <FilePreview key={entry.path} conversationId={conversationId} entry={entry} />
                  </div>
                ) : entry.type === "link" ? (
                  <p className={`p-3 ${NOTE}`}>{t("files.linkPreview")}</p>
                ) : entry.type === "other" ? (
                  // A FIFO, a socket or a device: never read (ADR-0129).
                  <p className={`p-3 ${NOTE}`}>{t("files.otherPreview")}</p>
                ) : undefined}
              </CodeFrame>
            </section>
          )}
        </div>
        {quota && (
          <div className="flex flex-none flex-col gap-2 border-t border-line px-4 py-3">
            <p className="text-caption text-ink-3 tabular-nums">{t("files.quota", { used: formatSize(quota.size), quota: formatSize(quota.quota) })}</p>
            <Meter label={t("files.quotaLabel")} value={quota.size} max={quota.quota} text={t("files.quota", { used: formatSize(quota.size), quota: formatSize(quota.quota) })} />
          </div>
        )}
        {/* A file larger, as a document or an app of its own (ART-001, ADR-0086). */}
        <Viewer open={large !== null} onClose={() => setLarge(null)} title={large?.name} description={t("files.fullViewHint")} closeLabel={t("files.close")}>
          {large !== null && <FilePreview conversationId={conversationId} entry={large} large />}
        </Viewer>
        {(asking?.kind === "delete" || asking?.kind === "reset") && (
          <Dialog
            asks
            size="sm"
            onClose={() => setAsking(null)}
            title={asking.kind === "reset" ? t("files.resetTitle") : t("files.deleteTitle", { name: asking.entry.name })}
            description={asking.kind === "reset" ? t("files.resetBody") : asking.entry.type === "folder" ? t("files.deleteFolderBody", { name: asking.entry.name }) : t("files.deleteBody", { name: asking.entry.name })}
            footer={
              <>
                <Button onClick={() => setAsking(null)}>{t("files.cancel")}</Button>
                <Button
                  variant="danger-solid"
                  busy={actions.busy("asked")}
                  onClick={() =>
                    asking.kind === "reset"
                      ? void run(() => resetWorkspace(conversationId), () => setSelected(null))
                      : void run(() => deleteEntry(conversationId, asking.entry.path), () => setSelected(null))
                  }
                >
                  {asking.kind === "reset" ? t("files.resetConfirm") : t("files.delete")}
                </Button>
              </>
            }
          />
        )}
        {(asking?.kind === "rename" || asking?.kind === "folder") && (
          <PathForm
            title={asking.kind === "rename" ? t("files.renameTitle") : t("files.newFolder")}
            label={t("files.pathLabel")}
            initial={asking.kind === "rename" ? asking.entry.path : asking.kind === "folder" && asking.in ? `${asking.in}/` : ""}
            confirm={asking.kind === "rename" ? t("files.renameConfirm") : t("files.create")}
            busy={actions.busy("asked")}
            onClose={() => setAsking(null)}
            onSubmit={(path) =>
              asking.kind === "rename"
                ? void run(() => moveEntry(conversationId, asking.entry.path, path), () => setSelected(path))
                : void run(() => createFolder(conversationId, path), () => setExpanded((all) => new Set(all).add(parentOf(path))))
            }
          />
        )}
      </div>
    </>
  );
}

function PathForm(props: { title: string; label: string; initial: string; confirm: string; busy: boolean; onClose: () => void; onSubmit: (path: string) => void }) {
  const { t } = useTranslation();
  return (
    <Dialog
      size="sm"
      onClose={props.onClose}
      title={props.title}
      onSubmit={(event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const path = String(new FormData(event.currentTarget).get("path") ?? "")
          .trim()
          .replace(/^\/+|\/+$/g, "");
        if (path) props.onSubmit(path);
      }}
      footer={
        <>
          <Button size="sm" onClick={props.onClose}>
            {t("files.cancel")}
          </Button>
          <Button size="sm" type="submit" variant="primary" busy={props.busy}>
            {props.confirm}
          </Button>
        </>
      }
    >
      <FormField label={props.label}>{(ties) => <TextInput {...ties} name="path" defaultValue={props.initial} autoFocus mono />}</FormField>
    </Dialog>
  );
}

interface TreeProps {
  conversationId: string;
  hidden: boolean;
  expanded: Set<string>;
  selected: string | null;
  onToggle: (path: string) => void;
  onSelect: (path: string) => void;
}

/** The workspace as a tree: folders load their entries when opened; arrows move between entries. */
function Tree(props: TreeProps) {
  const { t } = useTranslation();
  const root = useFolder(props.conversationId, "");
  const tree = useRef<HTMLUListElement>(null);
  const entries = (root.data ?? []).filter((entry) => props.hidden || !entry.name.startsWith("."));
  // The entry reached with Tab: the chosen one, or else the first.
  const focusable = props.selected ?? entries[0]?.path ?? null;

  function keyDown(event: KeyboardEvent<HTMLUListElement>) {
    const items = [...(tree.current?.querySelectorAll<HTMLElement>('[role="treeitem"]') ?? [])];
    const current = (event.target as HTMLElement).closest<HTMLElement>('[role="treeitem"]');
    const index = current === null ? -1 : items.indexOf(current);
    if (current === null || index === -1) return;
    const path = current.dataset.path ?? "";
    const isFolder = current.getAttribute("aria-expanded") !== null;
    const open = current.getAttribute("aria-expanded") === "true";
    const move = (to: HTMLElement | undefined) => {
      if (to === undefined) return;
      event.preventDefault();
      to.focus();
    };
    switch (event.key) {
      case "ArrowDown":
        move(items[index + 1]);
        break;
      case "ArrowUp":
        move(items[index - 1]);
        break;
      case "Home":
        move(items[0]);
        break;
      case "End":
        move(items.at(-1));
        break;
      case "ArrowRight":
        event.preventDefault();
        if (isFolder && !open) props.onToggle(path);
        else if (open) move(items[index + 1]);
        break;
      case "ArrowLeft":
        event.preventDefault();
        if (open) props.onToggle(path);
        else move(current.parentElement?.parentElement?.closest("li")?.querySelector<HTMLElement>(':scope > [role="treeitem"]') ?? undefined);
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        props.onSelect(path);
        if (isFolder) props.onToggle(path);
        break;
    }
  }

  return (
    <>
      <ul ref={tree} role="tree" aria-label={t("files.workspace")} onKeyDown={keyDown} className="flex min-h-16 flex-col gap-px p-2">
        {entries.map((entry) => (
          <TreeItem key={entry.path} {...props} entry={entry} level={1} focusable={focusable} />
        ))}
      </ul>
      {root.isPending && (
        <div className="-mt-12">
          <Loading compact />
        </div>
      )}
      {root.isSuccess && entries.length === 0 && <p className={`-mt-12 px-4 pb-6 ${NOTE}`}>{t("files.empty")}</p>}
      {root.isError && <p className="-mt-12 px-4 pb-6 text-small text-danger">{t("files.errors.sandbox_unavailable")}</p>}
    </>
  );
}

function TreeItem(props: TreeProps & { entry: WorkspaceEntry; level: number; focusable: string | null }) {
  const { entry, level } = props;
  const folder = entry.type === "folder";
  const open = folder && props.expanded.has(entry.path);
  const children = useFolder(props.conversationId, entry.path, open);
  const shown = (children.data ?? []).filter((child) => props.hidden || !child.name.startsWith("."));
  const Icon = folder ? Folder : entry.type === "link" ? Link2 : File;
  // The row is the treeitem, named by its own content; the folder's group sits beside it.
  return (
    <li role="none" className="flex flex-col gap-px">
      <TreeEntry
        level={level}
        path={entry.path}
        selected={props.selected === entry.path}
        expanded={folder ? open : undefined}
        focusable={props.focusable === entry.path}
        icon={<Icon aria-hidden="true" />}
        end={
          <>
            {entry.type === "file" && <span>{formatSize(entry.size)}</span>}
            <span>{new Date(entry.modified).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span>
          </>
        }
        onClick={() => {
          props.onSelect(entry.path);
          if (folder) props.onToggle(entry.path);
        }}
      >
        {entry.name}
      </TreeEntry>
      {open && (
        <ul role="group" className="flex flex-col gap-px">
          {shown.map((child) => (
            <TreeItem key={child.path} {...props} entry={child} level={level + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** A file shown as what it is, never run in the app: text as text, media in the browser's own players (UX-020). */
/** Kinds that have a source to show beside their preview. */
const WITH_SOURCE = new Set(["markdown", "diagram", "page"]);

function FilePreview({ conversationId, entry, large = false }: { conversationId: string; entry: WorkspaceEntry; large?: boolean }) {
  const { t } = useTranslation();
  const kind = previewKind(entry.name);
  const [showSource, setShowSource] = useState(false);
  const textual = kind === "text" || kind === "code" || kind === "markdown" || kind === "csv" || kind === "diagram" || (kind === "page" && showSource);
  const content = useQuery({
    queryKey: [...workspaceKey(conversationId), "preview", entry.path, entry.modified],
    queryFn: async () => {
      const response = await fetch(previewUrl(conversationId, entry.path), { credentials: "same-origin" });
      if (!response.ok) throw new ApiError(response.status, "file.not_previewable");
      return response.text();
    },
    enabled: textual,
  });
  const source = previewUrl(conversationId, entry.path);
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [entry.path, entry.modified]);
  const height = large ? "h-full" : "h-(--preview-limit)";
  const tall = large ? "max-h-none" : "max-h-(--preview-limit)";

  if (kind === "none" || broken || content.isError) return <p className={NOTE}>{t("files.noPreview")}</p>;
  if (kind === "image") return <img src={source} alt={entry.name} onError={() => setBroken(true)} style={PREVIEW_LIMIT} className={`${tall} max-w-full rounded-sm border border-line bg-surface object-contain`} />;
  if (kind === "pdf") return <iframe src={source} title={entry.name} style={PREVIEW_LIMIT} className={`${height} w-full rounded-sm border border-line bg-surface`} />;
  if (kind === "audio") return <audio src={source} controls className="w-full" aria-label={entry.name} onError={() => setBroken(true)} />;
  if (kind === "video") return <video src={source} controls style={PREVIEW_LIMIT} className={`${tall} w-full rounded-sm`} aria-label={entry.name} onError={() => setBroken(true)} />;

  const toggle = WITH_SOURCE.has(kind) && (
    <div className="mb-2 flex justify-end">
      <Button size="sm" onClick={() => setShowSource(!showSource)}>
        {showSource ? t("files.showPreview") : t("files.showSource")}
      </Button>
    </div>
  );
  // A web page runs in a sandboxed frame, a stranger to the app with no network (ART-003, ADR-0086).
  if (kind === "page" && !showSource) {
    return (
      <div className={large ? "flex h-full flex-col" : ""}>
        {toggle}
        <iframe src={pageUrl(conversationId, entry.path)} sandbox="allow-scripts" title={entry.name} style={PREVIEW_LIMIT} className={`${height} w-full rounded-sm border border-line bg-white`} />
      </div>
    );
  }
  if (content.data === undefined) return <Loading compact label={t("files.loading")} />;
  const truncated = TEXT_PREVIEW_BYTES < entry.size;
  const cut = truncated ? <p className="mt-2 text-caption text-ink-2">{t("files.cut")}</p> : null;
  if (showSource || kind === "code") {
    const language = kind === "markdown" ? "markdown" : kind === "page" ? "html" : kind === "diagram" ? "text" : languageOf(entry.name);
    return (
      <div>
        {toggle}
        {/* In the panel the code is already inside the preview's frame. */}
        <CodeBlock code={content.data} language={language} flush={!large} />
        {cut}
      </div>
    );
  }
  if (kind === "markdown") {
    return (
      <div>
        {toggle}
        <Markdown text={content.data} />
        {cut}
      </div>
    );
  }
  if (kind === "diagram") {
    return (
      <div>
        {toggle}
        <Diagram text={content.data} name={entry.name} large={large} />
      </div>
    );
  }
  if (kind === "csv") {
    const rows = parseCsv(content.data, CSV_ROWS);
    const [head, ...body] = rows;
    return (
      <div className="overflow-x-auto">
        <table className="text-small">
          {head && (
            <thead>
              <tr>
                {head.map((cell, index) => (
                  <th key={index} className="border border-line bg-hover px-2 py-1 text-left font-semibold whitespace-nowrap">
                    {cell}
                  </th>
                ))}
              </tr>
            </thead>
          )}
          <tbody>
            {body.map((row, index) => (
              <tr key={index}>
                {row.map((cell, column) => (
                  <td key={column} className="border border-line px-2 py-1 whitespace-nowrap">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {cut}
      </div>
    );
  }
  return (
    <>
      <pre tabIndex={0} style={PREVIEW_LIMIT} className="max-h-(--preview-limit) overflow-auto rounded-sm bg-hover p-3 font-mono text-small whitespace-pre-wrap break-words">
        {content.data}
      </pre>
      {cut}
    </>
  );
}

/** A Mermaid diagram, drawn in the app with its strict security level and shown as an image, which runs no scripts (ADR-0086). */
function Diagram({ text, name, large }: { text: string; name: string; large: boolean }) {
  const { t } = useTranslation();
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const [drawn, setDrawn] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let current = true;
    setFailed(false);
    void import("mermaid")
      .then(async ({ default: mermaid }) => {
        const dark = window.matchMedia("(prefers-color-scheme: dark)").matches || document.documentElement.dataset.theme === "dark";
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "default" });
        const { svg } = await mermaid.render(`diagram${id}`, text);
        if (current) setDrawn(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);
      })
      .catch(() => current && setFailed(true));
    return () => {
      current = false;
    };
  }, [text, id]);
  if (failed) return <p className={NOTE}>{t("files.diagramFailed")}</p>;
  if (drawn === null) return <Loading compact label={t("files.loading")} />;
  // Mermaid sizes its drawing to its container: as an image it takes the panel's width, or fits the full view.
  const size = large ? "h-(--preview-limit) w-full" : "h-auto max-h-(--preview-limit) w-full";
  return <img src={drawn} alt={name} style={large ? DIAGRAM_LIMIT : PREVIEW_LIMIT} className={`${size} rounded-sm border border-line bg-surface object-contain p-2`} />;
}

/** The first rows of a CSV text, with quoted fields. */
export function parseCsv(text: string, limit: number): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length && rows.length < limit; index++) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        field += '"';
        index++;
      } else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"') quoted = true;
    else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[index + 1] === "\n") index++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else field += char;
  }
  if ((field || row.length > 0) && rows.length < limit) rows.push([...row, field]);
  return rows;
}
