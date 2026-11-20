// The Memory page of the user's settings (UX-027, MEM-001 to MEM-008, ADR-0095).
import { useQueryClient } from "@tanstack/react-query";
import { Brain, Plus, ShieldAlert } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ApiError, api, unwrap, type Schemas } from "../api/client";
import { MEMORY, useMemory } from "../memory";
import { useNotify } from "../notices";
import { Button, Card, Dialog, EmptyState, FormField, Group, Notice, Page, Row, Switch, TextArea, Tile } from "../ui";

type MemoryItem = Schemas["MemoryItem"];

const ITEM_CHARS = 500;

/** The switch, the items newest first with where each came from, and adding, editing and deleting them. */
export function MemorySection() {
  const { t, i18n } = useTranslation();
  const field = useId();
  const more = useId();
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

  const on = switched ?? data?.enabled ?? false;
  const add = (
    <Button size="sm" onClick={() => setEditing("new")} disabled={!data}>
      <Plus aria-hidden="true" />
      {t("memory.add")}
    </Button>
  );

  return (
    <Page title={t("memory.title")} description={t("memory.hint")}>
      {data && (
        <Card rows>
          <Row title={t("memory.switch")} htmlFor={field} description={<span id={more}>{on ? t("memory.on") : t("memory.off")}</span>}>
            <Switch
              id={field}
              aria-describedby={more}
              checked={on}
              onChange={(enabled) => {
                setSwitched(enabled);
                void change(async () => unwrap(await api.PUT("/me/memory", { body: { enabled } }))).then(() => setSwitched(null));
              }}
            />
          </Row>
        </Card>
      )}
      <Group
        title={t("memory.items")}
        description={data ? t("memory.used", { used: number.format(data.used_characters), limit: number.format(data.limit_characters) }) : undefined}
        action={
          items.length > 0 && (
            <div className="flex flex-none flex-wrap justify-end gap-2">
              <Button size="sm" variant="danger" onClick={() => setClearing(true)}>
                {t("memory.deleteAll")}
              </Button>
              {add}
            </div>
          )
        }
      >
        <Card rows>
          {items.length === 0 ? (
            data && <EmptyState icon={<Brain />} title={t("memory.none")} action={add} />
          ) : (
            <ul aria-label={t("memory.items")} className="divide-y divide-line">
              {items.map((item) => (
                <MemoryEntry
                  key={item.id}
                  item={item}
                  onEdit={() => setEditing(item)}
                  onDelete={() => void change(async () => unwrap(await api.DELETE("/me/memory/items/{memory_item_id}", { params: { path: { memory_item_id: item.id } } })))}
                />
              ))}
            </ul>
          )}
        </Card>
      </Group>
      {editing !== null && <ItemDialog key={editing === "new" ? "new" : editing.id} item={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={refresh} />}
      {clearing && (
        <Dialog
          asks
          size="sm"
          onClose={() => setClearing(false)}
          title={t("memory.deleteAllTitle")}
          description={t("memory.deleteAllBody", { count: items.length })}
          footer={
            <>
              <Button onClick={() => setClearing(false)}>{t("memory.cancel")}</Button>
              <Button
                variant="danger-solid"
                onClick={() => {
                  setClearing(false);
                  void change(async () => unwrap(await api.DELETE("/me/memory/items")));
                }}
              >
                {t("memory.deleteAll")}
              </Button>
            </>
          }
        />
      )}
    </Page>
  );
}

/** One item: its text, when it was written, by whom or in which chat, and whether it is untrusted (MEM-005, MEM-008). */
function MemoryEntry({ item, onEdit, onDelete }: { item: MemoryItem; onEdit: () => void; onDelete: () => void }) {
  const { t, i18n } = useTranslation();
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" }).format(new Date(item.updated_at));
  const conversation = item.conversation;
  return (
    <li>
      <Row
        title={<span className="min-w-0 font-normal break-words whitespace-pre-wrap">{item.text}</span>}
        description={
          <>
            {date}
            {" · "}
            {conversation === null || conversation === undefined ? (
              t("memory.byYou")
            ) : conversation.deleted ? (
              t("memory.fromDeletedChat")
            ) : (
              <>
                {t("memory.fromChat")}{" "}
                <Link to={`/c/${conversation.id}`} className="font-semibold text-ink underline underline-offset-2">
                  {conversation.title || t("memory.untitledChat")}
                </Link>
              </>
            )}
          </>
        }
        below={
          <>
            {item.untrusted && (
              <Notice tone="warn" role="note" icon={<ShieldAlert aria-hidden="true" />} title={t("memory.untrusted")}>
                {t("memory.untrustedHint")}
              </Notice>
            )}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={onEdit} aria-label={t("memory.editLabel", { text: item.text })}>
                {t("memory.edit")}
              </Button>
              <Button size="sm" variant="danger" onClick={onDelete} aria-label={t("memory.deleteLabel", { text: item.text })}>
                {t("memory.delete")}
              </Button>
            </div>
          </>
        }
      />
    </li>
  );
}

/** Adding an item, or editing one: saving makes it the user's, which confirms an untrusted one (MEM-002, MEM-008). */
function ItemDialog({ item, onClose, onSaved }: { item: MemoryItem | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const { t } = useTranslation();
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
    <Dialog
      onClose={onClose}
      onSubmit={(event) => void save(event)}
      title={item === null ? t("memory.addTitle") : t("memory.editTitle")}
      description={item?.untrusted ? t("memory.confirmHint") : t("memory.itemHint")}
      leading={
        <Tile>
          <Brain />
        </Tile>
      }
      footer={
        <>
          <Button onClick={onClose}>{t("memory.cancel")}</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={value.trim() === ""}>
            {t("memory.save")}
          </Button>
        </>
      }
    >
      <FormField label={t("memory.text")} hint={t("memory.length", { count: value.trim().length, limit: ITEM_CHARS })} error={error}>
        {(ties) => <TextArea {...ties} required maxLength={ITEM_CHARS} value={value} onChange={(event) => setValue(event.target.value)} />}
      </FormField>
    </Dialog>
  );
}
