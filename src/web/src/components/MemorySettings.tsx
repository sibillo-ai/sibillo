// The Memory page of the user's settings (UX-027, MEM-001 to MEM-008, ADR-0095).
import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Brain, Plus, ShieldAlert } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ApiError, api, unwrap, type Schemas } from "../api/client";
import { MEMORY, useMemory } from "../memory";
import { useNotify } from "../notices";
import { Switch } from "./AssistantSettings";

type MemoryItem = Schemas["MemoryItem"];

const ITEM_CHARS = 500;
const BUTTON = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-hover disabled:opacity-50";
const SMALL = "inline-flex h-8 items-center justify-center rounded-[10px] border border-line-strong bg-surface px-3 text-[13px] font-semibold hover:bg-hover disabled:opacity-50";
const PRIMARY = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg disabled:opacity-50";
const DANGER = "h-[38px] rounded-[10px] bg-danger px-4 text-sm font-semibold text-on-danger disabled:opacity-50";
const TEXTAREA = "min-h-24 w-full rounded-[10px] border border-line-strong bg-bg px-3 py-2 text-sm outline-none focus:border-accent";
const DIALOG = "slide fixed top-1/2 left-1/2 z-50 w-[min(92vw,30rem)] -translate-x-1/2 -translate-y-1/2 rounded-[20px] bg-raised p-[22px] shadow-soft";

/** The switch, the items newest first with where each came from, and adding, editing and deleting them. */
export function MemorySection() {
  const { t, i18n } = useTranslation();
  const heading = useId();
  const queries = useQueryClient();
  const notify = useNotify();
  const memory = useMemory();
  const [editing, setEditing] = useState<MemoryItem | "new" | null>(null);
  const [clearing, setClearing] = useState(false);
  // The switch moves at once; the server's answer follows.
  const [switched, setSwitched] = useState<boolean | null>(null);
  const number = new Intl.NumberFormat(i18n.language);
  const refresh = () => queries.invalidateQueries({ queryKey: MEMORY });
  const data = memory.data;
  const items = data?.items ?? [];

  async function change(work: () => Promise<unknown>) {
    try {
      await work();
    } catch {
      notify({ kind: "error", title: t("assistant.notSaved") });
    }
    await refresh();
  }

  return (
    <section aria-labelledby={heading} className="flex flex-col gap-3.5">
      <div>
        <h2 id={heading} className="mb-1 text-base font-bold">
          {t("memory.title")}
        </h2>
        <p className="max-w-[62ch] text-sm text-muted">{t("memory.hint")}</p>
      </div>
      {data && (
        <Switch
          strong
          label={t("memory.switch")}
          description={(switched ?? data.enabled) ? t("memory.on") : t("memory.off")}
          checked={switched ?? data.enabled}
          onChange={(enabled) => {
            setSwitched(enabled);
            void change(async () => unwrap(await api.PUT("/me/memory", { body: { enabled } }))).then(() => setSwitched(null));
          }}
        />
      )}
      {data && (
        <p className="text-[13px] text-muted">
          {t("memory.used", { used: number.format(data.used_characters), limit: number.format(data.limit_characters) })}
        </p>
      )}
      {data && items.length === 0 && <p className="text-sm text-muted">{t("memory.none")}</p>}
      <ul aria-label={t("memory.items")} className="flex flex-col gap-2">
        {items.map((item) => (
          <MemoryEntry
            key={item.id}
            item={item}
            onEdit={() => setEditing(item)}
            onDelete={() => void change(async () => unwrap(await api.DELETE("/me/memory/items/{memory_item_id}", { params: { path: { memory_item_id: item.id } } })))}
          />
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={BUTTON} onClick={() => setEditing("new")} disabled={!data}>
          <Plus className="size-[18px]" aria-hidden="true" />
          {t("memory.add")}
        </button>
        {items.length > 0 && (
          <button type="button" className={BUTTON} onClick={() => setClearing(true)}>
            {t("memory.deleteAll")}
          </button>
        )}
      </div>
      {editing !== null && <ItemDialog key={editing === "new" ? "new" : editing.id} item={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={refresh} />}
      {clearing && (
        <Dialog.Root open onOpenChange={(open) => !open && setClearing(false)}>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
            <Dialog.Content role="alertdialog" className={DIALOG}>
              <Dialog.Title className="mb-2 text-lg font-bold">{t("memory.deleteAllTitle")}</Dialog.Title>
              <Dialog.Description className="text-sm text-muted">{t("memory.deleteAllBody", { count: items.length })}</Dialog.Description>
              <div className="mt-[18px] flex flex-wrap justify-end gap-2">
                <Dialog.Close className={BUTTON}>{t("memory.cancel")}</Dialog.Close>
                <button
                  type="button"
                  className={DANGER}
                  onClick={() => {
                    setClearing(false);
                    void change(async () => unwrap(await api.DELETE("/me/memory/items")));
                  }}
                >
                  {t("memory.deleteAll")}
                </button>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      )}
    </section>
  );
}

/** One item: its text, when it was written, by whom or in which chat, and whether it is untrusted (MEM-005, MEM-008). */
function MemoryEntry({ item, onEdit, onDelete }: { item: MemoryItem; onEdit: () => void; onDelete: () => void }) {
  const { t, i18n } = useTranslation();
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" }).format(new Date(item.updated_at));
  const conversation = item.conversation;
  return (
    <li className={`flex flex-col gap-2 rounded-2xl border bg-surface px-4 py-3 ${item.untrusted ? "border-danger/50" : "border-line"}`}>
      <p className="break-words whitespace-pre-wrap">{item.text}</p>
      {item.untrusted && (
        <p className="flex items-start gap-1.5 text-[13px] text-danger">
          <ShieldAlert className="mt-px size-4 flex-none" aria-hidden="true" />
          <span>
            <b>{t("memory.untrusted")}</b> {t("memory.untrustedHint")}
          </span>
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <p className="min-w-0 flex-1 text-[13px] text-muted">
          {date}
          {" · "}
          {conversation === null || conversation === undefined ? (
            t("memory.byYou")
          ) : conversation.deleted ? (
            t("memory.fromDeletedChat")
          ) : (
            <>
              {t("memory.fromChat")}{" "}
              <Link to={`/c/${conversation.id}`} className="font-semibold text-fg underline underline-offset-2">
                {conversation.title || t("memory.untitledChat")}
              </Link>
            </>
          )}
        </p>
        <button type="button" className={SMALL} onClick={onEdit} aria-label={t("memory.editLabel", { text: item.text })}>
          {t("memory.edit")}
        </button>
        <button type="button" className={SMALL} onClick={onDelete} aria-label={t("memory.deleteLabel", { text: item.text })}>
          {t("memory.delete")}
        </button>
      </div>
    </li>
  );
}

/** Adding an item, or editing one: saving makes it the user's, which confirms an untrusted one (MEM-002, MEM-008). */
function ItemDialog({ item, onClose, onSaved }: { item: MemoryItem | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const { t } = useTranslation();
  const field = useId();
  const [value, setValue] = useState(item?.text ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = { text: value };
      if (item === null) unwrap(await api.POST("/me/memory/items", { body }));
      else unwrap(await api.PATCH("/me/memory/items/{memory_item_id}", { params: { path: { memory_item_id: item.id } }, body }));
      await onSaved();
      onClose();
    } catch (failure) {
      setError(failure instanceof ApiError && failure.code === "memory.full" ? t("memory.full") : t("assistant.notSaved"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className={DIALOG}>
          <Dialog.Title className="mb-2 flex items-center gap-2 text-lg font-bold">
            <Brain className="size-5 text-accent" aria-hidden="true" />
            {item === null ? t("memory.addTitle") : t("memory.editTitle")}
          </Dialog.Title>
          <Dialog.Description className="text-sm text-muted">{item?.untrusted ? t("memory.confirmHint") : t("memory.itemHint")}</Dialog.Description>
          <form onSubmit={(event) => void save(event)} className="mt-3.5 flex flex-col gap-3.5">
            <label htmlFor={field} className="flex flex-col gap-1.5">
              <span className="text-[13.5px] font-semibold">{t("memory.text")}</span>
              <textarea id={field} required maxLength={ITEM_CHARS} value={value} onChange={(event) => setValue(event.target.value)} className={TEXTAREA} />
              <span className="text-[12.5px] text-muted">{t("memory.length", { count: value.trim().length, limit: ITEM_CHARS })}</span>
            </label>
            {error && (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Dialog.Close className={BUTTON}>{t("memory.cancel")}</Dialog.Close>
              <button type="submit" className={PRIMARY} disabled={busy || value.trim() === ""}>
                {t("memory.save")}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
