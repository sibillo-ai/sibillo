import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router";
import { Ellipsis } from "lucide-react";

import type { Conversation, Folder } from "../api/client";
import { deleteConversation, updateConversation, useRefreshConversations } from "../conversations";
import { Button, Dialog, FormField, IconButton, Menu, MenuItem, MenuSub, TextInput } from "../ui";

/** Rename, archive or delete a conversation (API-003). */
export function ConversationMenu({ conversation, folders }: { conversation: Conversation; folders: Folder[] }) {
  const { t } = useTranslation();
  const refresh = useRefreshConversations();
  const navigate = useNavigate();
  const { conversationId } = useParams();
  const [dialog, setDialog] = useState<"rename" | "delete" | null>(null);
  const title = conversation.title || t("shell.untitled");

  async function leaveIfOpen() {
    if (conversationId === conversation.id) await navigate("/");
  }

  async function change(changes: Parameters<typeof updateConversation>[1]) {
    await updateConversation(conversation.id, changes);
    await refresh();
  }

  async function rename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("title") ?? "").trim();
    if (name) await updateConversation(conversation.id, { title: name });
    setDialog(null);
    await refresh();
  }

  async function archive() {
    await updateConversation(conversation.id, { archived: true });
    await leaveIfOpen();
    await refresh();
  }

  async function remove() {
    await deleteConversation(conversation.id);
    setDialog(null);
    await leaveIfOpen();
    await refresh();
  }

  return (
    <>
      {/* The button shows when its row is pointed at, when it has the focus, while its menu is open, and where nothing hovers. */}
      <span className="flex flex-none opacity-0 group-hover:opacity-100 focus-within:opacity-100 has-aria-expanded:opacity-100 [@media(hover:none)]:opacity-100">
        <Menu
         
          trigger={
            <IconButton label={t("conversationMenu.label", { title })}>
              <Ellipsis aria-hidden="true" />
            </IconButton>
          }
        >
          <MenuItem onSelect={() => setDialog("rename")}>{t("conversationMenu.rename")}</MenuItem>
          <MenuItem onSelect={() => void change({ pinned: !conversation.pinned })}>{conversation.pinned ? t("conversationMenu.unpin") : t("conversationMenu.pin")}</MenuItem>
          {/* A conversation is in at most one folder (CNV-007). */}
          <MenuSub label={t("conversationMenu.move")}>
            {folders.map((folder) => (
              <MenuItem key={folder.id} disabled={conversation.folder_id === folder.id} onSelect={() => void change({ folder_id: folder.id })}>
                {folder.name}
              </MenuItem>
            ))}
            {conversation.folder_id !== null && <MenuItem onSelect={() => void change({ folder_id: null })}>{t("conversationMenu.noFolder")}</MenuItem>}
            {folders.length === 0 && <p className="p-2 text-small text-ink-2">{t("conversationMenu.noFolders")}</p>}
          </MenuSub>
          <MenuItem onSelect={() => void archive()}>{t("conversationMenu.archive")}</MenuItem>
          <MenuItem danger onSelect={() => setDialog("delete")}>
            {t("conversationMenu.delete")}
          </MenuItem>
        </Menu>
      </span>
      {dialog === "rename" && (
        <Dialog
          size="sm"
          onClose={() => setDialog(null)}
          title={t("conversationMenu.rename")}
          description={t("conversationMenu.renamePrompt")}
          descriptionHidden
          onSubmit={(event) => void rename(event)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>{t("conversationMenu.cancel")}</Button>
              <Button type="submit" variant="primary">
                {t("conversationMenu.save")}
              </Button>
            </>
          }
        >
          <FormField label={t("conversationMenu.renamePrompt")}>{(ties) => <TextInput {...ties} name="title" defaultValue={conversation.title} maxLength={200} autoFocus />}</FormField>
        </Dialog>
      )}
      {dialog === "delete" && (
        <Dialog
          asks
          size="sm"
          onClose={() => setDialog(null)}
          title={t("conversationMenu.deleteTitle")}
          description={t("conversationMenu.deleteBody")}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>{t("conversationMenu.cancel")}</Button>
              <Button variant="danger-solid" onClick={() => void remove()}>
                {t("conversationMenu.confirmDelete")}
              </Button>
            </>
          }
        />
      )}
    </>
  );
}
