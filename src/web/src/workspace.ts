// A conversation's workspace: browsing, previews, uploads and downloads (UX-019, CNV-017, ADR-0079).
import { useCallback, useRef, useState } from "react";

import { API_BASE, REQUEST_HEADER, type Schemas, api, unwrap, ApiError } from "./api/client";

export type WorkspaceEntry = Schemas["WorkspaceEntry"];
export type WorkspaceSummary = Schemas["WorkspaceSummary"];

/** An attachment once uploaded, as a run takes it and the history shows it (CNV-017). */
export interface AttachedFile {
  path: string;
  size: number;
}

/** A file the user attached to a message, as the composer shows it while it uploads. */
export interface Attachment {
  key: string;
  name: string;
  size: number;
  progress: number;
  path?: string;
  error?: string;
  // An image's preview, from the file on the device (UX-036).
  preview?: string;
}

/** The images a preview is shown for, by their type and by their extension (UX-036, ADR-0110). */
const IMAGE_TYPES: Record<string, string> = { "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp" };
const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp"]);

export function isImagePath(path: string): boolean {
  const dot = path.lastIndexOf(".");
  return dot > 0 && IMAGE_EXTENSIONS.has(path.slice(dot + 1).toLowerCase());
}

/** Pasted files as they are attached: an image without a name of its own is named `pasted-image` (UX-036). */
export function pastedFiles(files: File[]): File[] {
  return files.map((file) => {
    const extension = IMAGE_TYPES[file.type];
    const unnamed = file.name === "" || /^image\.[a-z]+$/i.test(file.name);
    return extension !== undefined && unnamed ? new File([file], `pasted-image.${extension}`, { type: file.type }) : file;
  });
}

const base = (conversationId: string) => `${API_BASE}/conversations/${conversationId}/workspace`;

export async function listFolder(conversationId: string, path: string): Promise<WorkspaceEntry[]> {
  const result = await api.GET("/conversations/{conversation_id}/workspace/entries", {
    params: { path: { conversation_id: conversationId }, query: { path } },
  });
  return unwrap(result).entries;
}

export async function workspaceSummary(conversationId: string): Promise<WorkspaceSummary> {
  return unwrap(await api.GET("/conversations/{conversation_id}/workspace", { params: { path: { conversation_id: conversationId } } }));
}

export async function deleteEntry(conversationId: string, path: string): Promise<void> {
  const result = await api.DELETE("/conversations/{conversation_id}/workspace/entries", {
    params: { path: { conversation_id: conversationId }, query: { path } },
  });
  if (!result.response.ok) unwrap(result);
}

export async function resetWorkspace(conversationId: string): Promise<void> {
  const result = await api.DELETE("/conversations/{conversation_id}/workspace", { params: { path: { conversation_id: conversationId } } });
  if (!result.response.ok) unwrap(result);
}

export async function createFolder(conversationId: string, path: string): Promise<WorkspaceEntry> {
  return unwrap(
    await api.POST("/conversations/{conversation_id}/workspace/folders", { params: { path: { conversation_id: conversationId } }, body: { path } }),
  );
}

export async function moveEntry(conversationId: string, from: string, to: string): Promise<WorkspaceEntry> {
  return unwrap(
    await api.POST("/conversations/{conversation_id}/workspace/move", { params: { path: { conversation_id: conversationId } }, body: { from, to } }),
  );
}

/** Where a file is downloaded from, as an attachment; the session cookie authenticates the request. */
export function downloadUrl(conversationId: string, path: string): string {
  return `${base(conversationId)}/file?path=${encodeURIComponent(path)}`;
}

/** Where a file is previewed from, with one of the safe types (UX-020). */
export function previewUrl(conversationId: string, path: string): string {
  return `${downloadUrl(conversationId, path)}&preview=true`;
}

/** Where a web page runs from: a sandboxed document with an opaque origin and no network (ART-003, ADR-0086). */
export function pageUrl(conversationId: string, path: string): string {
  return `${downloadUrl(conversationId, path)}&page=true`;
}

export function archiveUrl(conversationId: string, path: string): string {
  return `${base(conversationId)}/archive?path=${encodeURIComponent(path)}`;
}

/** Start a download, without loading the file into the page. */
export function download(url: string): void {
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  link.rel = "noopener";
  document.body.append(link);
  link.click();
  link.remove();
}

/** An upload in progress. Once its body is `sent`, aborting no longer stops the server from saving it. */
export interface Transfer {
  done: Promise<WorkspaceEntry>;
  abort: () => void;
  sent: () => boolean;
}

/** Upload a file, reporting progress: into `uploads/` under a free name, or to `path` exactly. */
export function upload(
  conversationId: string,
  file: File,
  onProgress: (fraction: number) => void,
  path?: string,
): Transfer {
  const request = new XMLHttpRequest();
  let sent = false;
  const url = path === undefined ? `${base(conversationId)}/uploads?name=${encodeURIComponent(file.name)}` : `${base(conversationId)}/file?path=${encodeURIComponent(path)}`;
  const done = new Promise<WorkspaceEntry>((resolve, reject) => {
    request.open(path === undefined ? "POST" : "PUT", url);
    request.withCredentials = true;
    for (const [name, value] of Object.entries(REQUEST_HEADER)) request.setRequestHeader(name, value);
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    request.upload.onload = () => {
      sent = true;
    };
    request.onload = () => {
      if (request.status === 201) {
        resolve(JSON.parse(request.responseText) as WorkspaceEntry);
        return;
      }
      let code = "internal.error";
      try {
        code = (JSON.parse(request.responseText) as { code?: string }).code ?? code;
      } catch {
        // Not a problem document.
      }
      reject(new ApiError(request.status, code));
    };
    request.onerror = () => reject(new ApiError(0, "network"));
    request.onabort = () => reject(new ApiError(0, "aborted"));
    request.send(file);
  });
  return { done, abort: () => request.abort(), sent: () => sent };
}

/** A size for people: 24 KB, 3.1 MB. */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/** The kind of preview a file gets, by its extension, as the API serves it (UX-020). */
export type PreviewKind = "text" | "code" | "markdown" | "csv" | "diagram" | "page" | "image" | "pdf" | "audio" | "video" | "none";

// Source code, highlighted in its language (ART-002, ADR-0086).
const CODE_EXTENSIONS = new Set("json yaml yml toml ini cfg py js ts tsx jsx css sh sql xml c h rs go java rb".split(" "));
const KINDS: Record<string, PreviewKind> = {
  txt: "text",
  log: "text",
  md: "markdown",
  // Diagrams, drawn; web pages, run (ART-002, ART-003).
  mmd: "diagram",
  mermaid: "diagram",
  html: "page",
  htm: "page",
  csv: "csv",
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  svg: "image",
  pdf: "pdf",
  mp3: "audio",
  ogg: "audio",
  wav: "audio",
  m4a: "audio",
  mp4: "video",
  webm: "video",
};

export function previewKind(name: string): PreviewKind {
  const dot = name.lastIndexOf(".");
  const extension = dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
  return CODE_EXTENSIONS.has(extension) ? "code" : (KINDS[extension] ?? "none");
}

/** The language a file's code is highlighted in, from its extension. */
export function languageOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "text";
}

/** The files attached to the message being written: each uploads as soon as it is picked (CNV-017). */
export function useAttachments(conversation: () => Promise<string>) {
  const [items, setItems] = useState<Attachment[]>([]);
  const transfers = useRef(new Map<string, Transfer>());
  const owner = useRef<string | null>(null);
  // Deletions of removed attachments, which later uploads wait for: a file pasted again after its
  // removal then takes its name back instead of a numbered one (ADR-0079).
  const deleting = useRef<Promise<unknown>>(Promise.resolve());

  const update = useCallback((key: string, change: Partial<Attachment>) => {
    setItems((all) => all.map((item) => (item.key === key ? { ...item, ...change } : item)));
  }, []);

  const add = useCallback(
    (files: File[]) => {
      const added: Attachment[] = files.map((file) => ({
        key: crypto.randomUUID(),
        name: file.name,
        size: file.size,
        progress: 0,
        ...(file.type in IMAGE_TYPES ? { preview: URL.createObjectURL(file) } : {}),
      }));
      setItems((all) => [...all, ...added]);
      void Promise.all([conversation(), deleting.current]).then(
        ([conversationId]) => {
          owner.current = conversationId;
          added.forEach((item, index) => {
            const file = files[index];
            if (file === undefined) return;
            const transfer = upload(conversationId, file, (progress) => update(item.key, { progress }));
            transfers.current.set(item.key, transfer);
            transfer.done.then(
              (entry) => update(item.key, { progress: 1, path: entry.path, name: entry.name }),
              (error: unknown) => update(item.key, { error: error instanceof ApiError ? error.code : "internal.error" }),
            );
            void transfer.done.finally(() => transfers.current.delete(item.key)).catch(() => undefined);
          });
        },
        (error: unknown) => {
          const code = error instanceof ApiError ? error.code : "internal.error";
          for (const item of added) update(item.key, { error: code });
        },
      );
    },
    [conversation, update],
  );

  /**
   * Removing an attachment before sending deletes its file (CNV-017): an upload whose body is not
   * sent yet is stopped, and the server keeps nothing of it; one already sent is let finish, since
   * the server may have saved it, and its file is then deleted.
   */
  const remove = useCallback(
    (key: string) => {
      const item = items.find((candidate) => candidate.key === key);
      setItems((all) => all.filter((candidate) => candidate.key !== key));
      if (item?.preview !== undefined) URL.revokeObjectURL(item.preview);
      const conversationId = owner.current;
      if (conversationId === null) return;
      const transfer = transfers.current.get(key);
      let deleted: Promise<unknown> | undefined;
      if (transfer !== undefined && !transfer.sent()) transfer.abort();
      else if (transfer !== undefined) deleted = transfer.done.then((entry) => deleteEntry(conversationId, entry.path));
      else if (item?.path !== undefined) deleted = deleteEntry(conversationId, item.path);
      if (deleted !== undefined) deleting.current = Promise.all([deleting.current, deleted.catch(() => undefined)]);
    },
    [items],
  );

  const clear = useCallback(() => {
    setItems((all) => {
      for (const item of all) if (item.preview !== undefined) URL.revokeObjectURL(item.preview);
      return [];
    });
  }, []);
  const uploading = items.some((item) => item.path === undefined && item.error === undefined);
  const ready: AttachedFile[] = items.flatMap((item) => (item.path === undefined ? [] : [{ path: item.path, size: item.size }]));
  return { items, add, remove, clear, uploading, ready };
}
