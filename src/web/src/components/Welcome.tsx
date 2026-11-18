import { Ghost, RefreshCw, Share2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import type { ModelChoice, User } from "../api/client";
import { createConversation, useRefreshConversations } from "../conversations";
import { useModels } from "../models";
import { useNotify } from "../notices";
import { messageOf, takeShare } from "../share";
import { type AttachedFile, useAttachments } from "../workspace";
import { Composer } from "./Composer";
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

  async function start(text: string, files: AttachedFile[], voice?: VoiceMode) {
    const id = await conversation();
    await refresh();
    await navigate(`/c/${id}`, { state: { firstMessage: text, attachments: files, voice } });
  }

  function another() {
    if (quotes.length < 2) return;
    let next = index;
    while (next === index) next = Math.floor(Math.random() * quotes.length);
    setIndex(next);
  }

  return (
    <div className="relative flex flex-1 overflow-y-auto">
      <button
        type="button"
        onClick={() => setTemporary(!temporary)}
        // Chosen before the chat exists: an attachment creates it.
        disabled={attachments.items.length > 0}
        aria-pressed={temporary}
        className="absolute top-3 right-3 flex items-center gap-1.5 rounded-[10px] border border-line-strong px-3 py-1.5 text-sm font-semibold text-muted hover:bg-hover hover:text-fg disabled:opacity-50 aria-pressed:border-fg aria-pressed:bg-fg aria-pressed:text-bg"
      >
        <Ghost className="size-4" aria-hidden="true" />
        {t("temporary.toggle")}
      </button>
      <div className="m-auto flex w-full max-w-[760px] flex-col gap-7 px-4 pt-14 pb-12">
        <div className="flex flex-col items-center justify-center gap-3.5 sm:flex-row sm:gap-2">
          <Sprite pose="greeting" className="h-[124px] w-[108px] flex-none sm:h-[152px] sm:w-[132px]" />
          {quote && (
            <figure className="relative m-0 max-w-[460px] rounded-[22px] border border-line bg-surface px-[22px] pt-[18px] pb-4 shadow-soft">
              <p className="mb-2 text-xl font-bold tracking-tight text-balance">{greeting}</p>
              {temporary && <p className="mb-2 text-sm text-muted">{t("temporary.hint")}</p>}
              <blockquote className="m-0 font-serif text-[19px] leading-[1.45] italic text-pretty">“{quote.text}”</blockquote>
              <figcaption className="mt-2 flex items-center gap-1.5 text-[13.5px] text-muted">
                <span className="flex-1">
                  {quote.author}
                  {quote.work && (
                    <>
                      , <cite>{quote.work}</cite>
                    </>
                  )}
                </span>
                <button type="button" onClick={another} className="grid size-8 place-items-center rounded-lg hover:bg-hover hover:text-fg" aria-label={t("welcome.anotherQuote")} title={t("welcome.anotherQuote")}>
                  <RefreshCw className="size-4" aria-hidden="true" />
                </button>
              </figcaption>
            </figure>
          )}
        </div>
        {draft !== null && (
          <p className="-mb-4 flex items-center gap-2 px-2 text-sm text-muted">
            <Share2 className="size-4 flex-none" aria-hidden="true" />
            {t("share.fromAnotherApp")}
          </p>
        )}
        <Composer
          key={draft?.key ?? 0}
          initialText={draft?.text ?? ""}
          onSend={(text, files, voice) => void start(text, files, voice)}
          attachments={attachments}
          running={false}
          model={model}
          onModel={setChosen}
          placeholder={t("welcome.placeholder")}
          autoFocus
        />
      </div>
    </div>
  );
}
