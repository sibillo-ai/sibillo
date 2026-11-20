import { Ghost, RefreshCw, Share2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import type { ModelChoice, User } from "../api/client";
import { createConversation, useRefreshConversations } from "../conversations";
import { useModels } from "../models";
import { useNotify } from "../notices";
import { messageOf, takeShare } from "../share";
import { Button, IconButton, TopBar } from "../ui";
import { type AttachedFile, useAttachments } from "../workspace";
import { Composer } from "./Composer";
import { ModelSelect } from "./ModelPicker";
import { MenuButton } from "./Shell";
import { Sprite } from "./Sprite";
import type { VoiceMode } from "../voice";

interface Quote {
  text: string;
  author: string;
  work: string;
}

/** A new chat: the sprite greets with a quote, and the conversation is created with its first message (UX-012). */
export function Welcome({ me }: { me: User }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const refresh = useRefreshConversations();
  const models = useModels();
  const [chosen, setChosen] = useState<ModelChoice | null>(null);
  // Not listed, and deleted when left (CNV-011).
  const [temporary, setTemporary] = useState(false);
  const quotes = t("quotes", { returnObjects: true }) as Quote[];
  const [index, setIndex] = useState(() => Math.floor(Math.random() * quotes.length));
  const quote = quotes[index % quotes.length];
  const model = chosen ?? models.data?.default ?? null;
  const hour = new Date().getHours();
  const name = me.display_name;
  const greeting = hour < 12 ? t("welcome.morning", { name }) : hour < 18 ? t("welcome.afternoon", { name }) : t("welcome.evening", { name });

  // The conversation is created with the first attachment, whose workspace receives it, or else with the first message.
  const created = useRef<Promise<string> | null>(null);
  const conversation = useCallback(() => {
    created.current ??= createConversation(chosen ?? undefined, temporary).then((made) => made.id);
    return created.current;
  }, [chosen, temporary]);
  const attachments = useAttachments(conversation);

  // A share from another app, which the service worker kept: offered once, and sent only by the user (UX-006, ADR-0102).
  const [params] = useSearchParams();
  const shared = params.get("shared") === "1";
  const notify = useNotify();
  const [draft, setDraft] = useState<{ text: string; key: number } | null>(null);
  const taking = useRef(false);
  const add = attachments.add;
  useEffect(() => {
    if (!shared || taking.current) return;
    taking.current = true;
    void (async () => {
      const share = await takeShare().catch(() => undefined);
      taking.current = false;
      await navigate("/", { replace: true });
      const text = share === undefined ? "" : messageOf(share);
      if (share === undefined || (text === "" && share.files.length === 0)) {
        notify({ kind: "error", title: t("share.nothing"), text: t("share.nothingHint") });
        return;
      }
      setDraft({ text, key: Date.now() });
      if (share.files.length > 0) add(share.files);
    })();
  }, [shared, navigate, notify, t, add]);

  async function start(text: string, files: AttachedFile[], voice?: VoiceMode, focused?: boolean) {
    const id = await conversation();
    await refresh();
    await navigate(`/c/${id}`, { state: { firstMessage: text, attachments: files, voice, focused } });
  }

  function another() {
    if (quotes.length < 2) return;
    let next = index;
    while (next === index) next = Math.floor(Math.random() * quotes.length);
    setIndex(next);
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
      {/* The top bar: on a phone the button for the conversation list, and the temporary chat at its end (UX-039). */}
      <TopBar start={<MenuButton />}>
        <Button
          // Ghost, as a toolbar's button is; with a border when it is on, which is what shows that it is.
          variant={temporary ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTemporary(!temporary)}
          // Chosen before the chat exists: an attachment creates it.
          disabled={attachments.items.length > 0}
          aria-pressed={temporary}
        >
          <Ghost aria-hidden="true" />
          {t("temporary.toggle")}
        </Button>
      </TopBar>
      {/* On a computer the greeting and the message box are centered together; on a phone the message box stays at the bottom. */}
      <div className="mx-auto flex w-full max-w-read flex-1 flex-col gap-8 px-4 pt-6 pb-4 md:justify-center md:px-6 md:pb-12">
        <div className="flex items-center gap-4 max-md:my-auto md:items-end md:gap-6">
          <Sprite pose="greeting" className="h-auto w-14 flex-none md:w-20" />
          <div className="min-w-0 flex-1">
            <h1 className="font-serif text-display text-balance">{greeting}</h1>
            {temporary && <p className="mt-1 text-small text-ink-2">{t("temporary.hint")}</p>}
            {quote && (
              <figure className="mt-2">
                <blockquote className="font-serif text-reading text-pretty text-ink-2 italic">“{quote.text}”</blockquote>
                <figcaption className="flex items-center gap-1 text-caption font-medium text-ink-3">
                  <span>
                    {quote.author}
                    {quote.work && (
                      <>
                        , <cite className="not-italic">{quote.work}</cite>
                      </>
                    )}
                  </span>
                  <IconButton label={t("welcome.anotherQuote")} onClick={another}>
                    <RefreshCw aria-hidden="true" />
                  </IconButton>
                </figcaption>
              </figure>
            )}
            {/* The model the chat starts with is chosen with the greeting, not in the message box (UX-039). */}
            <div className="-ml-3 mt-2 flex">
              <ModelSelect
                compact
                value={model}
                onChange={setChosen}
                {...(models.data && models.data.items.length > 0 ? { placeholder: t("composer.chooseModel") } : {})}
              />
            </div>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          {draft !== null && (
            <p className="flex items-center gap-2 px-2 text-small text-ink-2">
              <Share2 className="size-4 flex-none" aria-hidden="true" />
              {t("share.fromAnotherApp")}
            </p>
          )}
          <Composer
            key={draft?.key ?? 0}
            initialText={draft?.text ?? ""}
            onSend={(text, files, voice, focused) => void start(text, files, voice, focused)}
            attachments={attachments}
            running={false}
            model={model}
            placeholder={t("welcome.placeholder")}
            autoFocus
          />
        </div>
      </div>
    </div>
  );
}
