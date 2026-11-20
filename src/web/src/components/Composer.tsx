import { ArrowUp, Headphones, LoaderCircle, Mic, Paperclip, Square } from "lucide-react";
import { type ClipboardEvent, type DragEvent, type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ModelChoice } from "../api/client";
import { hasKeyboard } from "../focus";
import { findModel, refusedBy, useModels } from "../models";
import { type AttachedFile, formatSize, pastedFiles, type useAttachments } from "../workspace";
import { Recorder, transcribe } from "../speech";
import { VoiceLevel } from "./VoiceLevel";
import { useVoice, type VoiceMode } from "../voice";
import { useNotify } from "../notices";
import { Button, FileInput, IconButton } from "../ui";
import { Attachment, Attachments, MessageBar, MessageBox, MessageInput, SendButton } from "../ui/MessageBox";

/** The message box: Enter sends, Shift+Enter starts a new line; while a run goes on, Stop. Files attach by picking or dropping (CNV-017). */
export function Composer(props: {
  // `voice`: how the message came, when it was not typed (ADR-0088).
  // `focused`: whether the message box had the focus, which it keeps (UX-018).
  onSend: (text: string, attachments: AttachedFile[], voice?: VoiceMode, focused?: boolean) => void;
  attachments: ReturnType<typeof useAttachments>;
  onStop?: () => void;
  running: boolean;
  // The conversation's model, chosen elsewhere (UX-039): what it can do and where it runs is said here.
  model: ModelChoice | null;
  placeholder: string;
  // Take the focus when shown, on devices with a keyboard (UX-018).
  autoFocus?: boolean;
  // Take the focus when shown on any device: the box the message was sent from had it (UX-018).
  keepFocus?: boolean;
  // The text the box starts with, as what another app shared (UX-006).
  initialText?: string;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState(props.initialText ?? "");
  const models = useModels();
  const chosen = findModel(models.data?.items, props.model);
  const area = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const files = props.attachments;
  const voice = useVoice();
  const notify = useNotify();
  const recorder = useRef(new Recorder());
  const [dictation, setDictation] = useState<"off" | "recording" | "preparing">("off");
  // A hands-free turn is sent by the message box in view (UX-005).
  const onSend = useRef(props.onSend);
  onSend.current = props.onSend;
  useEffect(() => voice?.register((said, mode) => onSend.current(said, [], mode)), [voice?.register]);
  // Whether the box holds dictated words, which the assistant is told about (ADR-0088).
  const [dictated, setDictated] = useState(false);
  // The first message of a new chat was sent from a box with the focus: this one, in its conversation, takes it.
  const keepFocus = useRef(props.keepFocus === true);
  useEffect(() => {
    if (keepFocus.current) area.current?.focus();
  }, []);

  /** Dictation: the spoken turn becomes the text of the box, to review before sending (UX-005). */
  async function dictate() {
    if (dictation === "preparing") return;
    if (dictation === "off") {
      try {
        await recorder.current.start();
        setDictation("recording");
      } catch {
        notify({ kind: "error", title: t("voice.noMicrophone") });
      }
      return;
    }
    setDictation("preparing");
    try {
      const said = (await transcribe(await recorder.current.stop())).trim();
      if (said) {
        setText((now) => (now.trim() ? `${now.trimEnd()} ${said}` : said));
        setDictated(true);
      }
    } catch {
      notify({ kind: "error", title: t("voice.notHeard") });
    } finally {
      setDictation("off");
      requestAnimationFrame(() => area.current?.focus());
    }
  }

  useEffect(() => {
    const element = area.current;
    if (element === null) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 220)}px`;
  }, [text]);

  function send(event?: FormEvent) {
    event?.preventDefault();
    const message = text.trim();
    if (!message || props.running || files.uploading) return;
    // Sent from the box, by a key or its send button, the box keeps the focus for the next message (UX-018).
    const focused = area.current?.form?.contains(document.activeElement) ?? false;
    props.onSend(message, files.ready, dictated ? "dictated" : undefined, focused);
    setText("");
    setDictated(false);
    files.clear();
    if (focused) area.current?.focus();
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) send(event);
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length > 0) files.add([...event.dataTransfer.files]);
  }

  /** Pasted files and images attach as picked ones do; text is pasted as ever (UX-036). */
  function paste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const pasted = [...event.clipboardData.files];
    if (pasted.length === 0) return;
    event.preventDefault();
    files.add(pastedFiles(pasted));
  }

  // A model the user's data egress policy refuses, said before anything is sent (UX-024).
  const refused = refusedBy(models.data?.egress.effective, chosen);
  return (
    <MessageBox
      onSubmit={send}
      dropping={dragging}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={drop}
      // Whether the model can use tools (MOD-014); where the data goes is said by the model's button (MOD-010).
      caption={
        models.data && models.data.items.length === 0
          ? t("composer.noModel")
          : refused
            ? t("composer.refused")
            : chosen?.tools === false
              ? t("composer.chatOnly")
              : null
      }
    >
      {files.items.length > 0 && (
        <Attachments label={t("files.attachments")}>
          {files.items.map((item) => (
            <Attachment
              key={item.key}
              name={item.name}
              preview={item.preview}
              failed={Boolean(item.error)}
              detail={
                item.error
                  ? t(`files.errors.${errorKey(item.error)}`)
                  : item.path === undefined
                    ? item.progress >= 1
                      ? t("files.saving")
                      : t("files.uploading", { percent: Math.round(item.progress * 100) })
                    : formatSize(item.size)
              }
              removeLabel={t("files.remove", { name: item.name })}
              onRemove={() => files.remove(item.key)}
            />
          ))}
        </Attachments>
      )}
      <MessageInput
        id="composer"
        label={t("composer.label")}
        ref={area}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          // Cleared, the box holds no dictated words anymore.
          if (!event.target.value.trim()) setDictated(false);
        }}
        onKeyDown={keyDown}
        onPaste={paste}
        autoFocus={props.autoFocus === true && hasKeyboard()}
        placeholder={props.placeholder}
        hidden={dictation !== "off"}
      />
      {/* Dictation in the box itself: the voice as it is captured, and how to end it; then the wait (UX-005). */}
      {dictation === "recording" && recorder.current.stream && (
        <div className="flex items-center gap-3 px-2">
          <VoiceLevel stream={recorder.current.stream} label={t("voice.capturing")} className="min-w-0 flex-1 text-danger" />
          <Button variant="danger-solid" onClick={() => void dictate()} aria-label={t("voice.stopDictating")}>
            <Square fill="currentColor" aria-hidden="true" />
            {t("voice.stop")}
          </Button>
        </div>
      )}
      {dictation === "preparing" && (
        <p role="status" className="flex h-14 items-center gap-2 px-2 text-reading text-ink-2">
          <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          <span className="live-text">{t("voice.preparing")}</span>
        </p>
      )}
      <MessageBar
        start={
          <>
            <FileInput
              ref={picker}
              multiple
              hidden
              aria-label={t("files.attach")}
              onChange={(event) => {
                if (event.target.files) files.add([...event.target.files]);
                event.target.value = "";
              }}
            />
            <IconButton label={t("files.attachOne")} onClick={() => picker.current?.click()}>
              <Paperclip aria-hidden="true" />
            </IconButton>
            {voice?.transcription && dictation === "off" && (
              <IconButton
                label={t("voice.dictate")}
                onClick={() => void dictate()}
                disabled={voice.transcriptionRefused}
                // Unavailable, saying why, when only local models are allowed (UX-024).
                title={voice.transcriptionRefused ? t("voice.refused") : t("voice.dictate")}
              >
                <Mic aria-hidden="true" />
              </IconButton>
            )}
            {voice?.transcription && voice.speech && (
              <IconButton
                label={t("voice.handsFree")}
                onClick={voice.open}
                disabled={voice.transcriptionRefused || voice.speechRefused}
                title={voice.transcriptionRefused || voice.speechRefused ? t("voice.refused") : t("voice.handsFree")}
              >
                <Headphones aria-hidden="true" />
              </IconButton>
            )}
          </>
        }
        end={
          <>
            {props.running && props.onStop ? (
              <SendButton type="button" label={t("composer.stop")} onClick={props.onStop}>
                <Square fill="currentColor" aria-hidden="true" />
              </SendButton>
            ) : (
              <SendButton label={t("composer.send")} disabled={!text.trim() || files.uploading}>
                <ArrowUp aria-hidden="true" />
              </SendButton>
            )}
          </>
        }
      />
    </MessageBox>
  );
}

/** The translation key of an upload's error. */
export function errorKey(code: string): string {
  return ["file.too_large", "workspace.quota_exceeded", "resource.conflict", "sandbox.unavailable", "network"].includes(code) ? code.replace(".", "_") : "internal_error";
}
