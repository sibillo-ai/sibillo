// The Skills page of the user's settings (UX-028, AGT-017, AGT-024, AGT-025, ADR-0096).
import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Download, Plus, ShieldAlert, Sparkles, Upload, X } from "lucide-react";
import { type FormEvent, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { API_BASE, ApiError, api, unwrap, type Schemas } from "../api/client";
import { fileAddress, SKILLS, type Skill, type SkillDetail, skillDetail, uploadSkill, useSkills } from "../skills";
import { useNotify } from "../notices";

type Found = Schemas["SkillImport"]["found"][number];

const BUTTON = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-hover disabled:opacity-50";
const SMALL = "inline-flex h-8 items-center justify-center gap-1.5 rounded-[10px] border border-line-strong bg-surface px-3 text-[13px] font-semibold hover:bg-hover disabled:opacity-50";
const PRIMARY = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg disabled:opacity-50";
const DANGER = "h-[38px] rounded-[10px] bg-danger px-4 text-sm font-semibold text-on-danger disabled:opacity-50";
const INPUT = "h-10 w-full rounded-[10px] border border-line-strong bg-bg px-3 outline-none focus:border-accent";
const TEXTAREA = "min-h-64 w-full rounded-[10px] border border-line-strong bg-bg px-3 py-2 font-mono text-[13px] outline-none focus:border-accent";
const DIALOG = "slide fixed top-1/2 left-1/2 z-50 flex max-h-[min(92dvh,48rem)] w-[min(94vw,44rem)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-[20px] bg-raised p-[22px] shadow-soft";
const SWITCH =
  "relative h-6 w-10 flex-none rounded-full bg-line-strong transition-colors peer-checked:bg-accent peer-focus-visible:outline-2 peer-focus-visible:outline-accent after:absolute after:top-0.5 after:left-0.5 after:size-5 after:rounded-full after:bg-bg after:transition-transform peer-checked:after:translate-x-4";
const NEW_SKILL = "---\nname: my-skill\ndescription: Use when …\n---\n\n# My skill\n\nWhat to do, step by step.\n";

/** The built-in skills, then the user's, each with its switch; and creating, uploading and importing them. */
export function SkillsSection() {
  const { t, i18n } = useTranslation();
  const heading = useId();
  const queries = useQueryClient();
  const notify = useNotify();
  const skills = useSkills();
  const upload = useRef<HTMLInputElement>(null);
  const uploadLabel = useId();
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<Skill | null>(null);
  const [trusting, setTrusting] = useState<Skill | null>(null);
  const [deleting, setDeleting] = useState<Skill | null>(null);
  // A switch moves at once; the server's answer follows.
  const [switched, setSwitched] = useState<Record<string, boolean>>({});
  const refresh = () => queries.invalidateQueries({ queryKey: SKILLS });
  const data = skills.data;
  const number = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 });

  async function change(work: () => Promise<unknown>) {
    try {
      await work();
    } catch (failure) {
      notify({ kind: "error", title: t("skills.notSaved"), text: problemText(t, failure) });
    }
    await refresh();
  }

  async function toggle(skill: Skill, enabled: boolean) {
    const key = skill.id ?? skill.name;
    setSwitched((old) => ({ ...old, [key]: enabled }));
    await change(async () =>
      skill.id === null
        ? unwrap(await api.PATCH("/me/skills/builtin/{skill_name}", { params: { path: { skill_name: skill.name } }, body: { enabled } }))
        : unwrap(await api.PATCH("/me/skills/{skill_id}", { params: { path: { skill_id: skill.id } }, body: { enabled } })),
    );
    setSwitched((old) => Object.fromEntries(Object.entries(old).filter(([name]) => name !== key)));
  }
  const shown = (skill: Skill): Skill => ({ ...skill, enabled: switched[skill.id ?? skill.name] ?? skill.enabled });

  return (
    <section aria-labelledby={heading} className="flex flex-col gap-3.5">
      <div>
        <h2 id={heading} className="mb-1 text-base font-bold">
          {t("skills.title")}
        </h2>
        <p className="max-w-[62ch] text-sm text-muted">{t("skills.hint")}</p>
      </div>

      <h3 className="text-sm font-bold">{t("skills.builtin")}</h3>
      <ul aria-label={t("skills.builtin")} className="flex flex-col gap-2">
        {(data?.builtin ?? []).map((skill) => (
          <SkillEntry key={skill.name} skill={shown(skill)} onToggle={(on) => void toggle(skill, on)} onOpen={() => setOpen(skill)} />
        ))}
      </ul>

      <h3 className="mt-2 text-sm font-bold">{t("skills.own")}</h3>
      {data && (
        <p className="text-[13px] text-muted">
          {t("skills.used", { used: number.format(data.used_bytes / 1048576), limit: number.format(data.limit_bytes / 1048576), count: data.own.length, most: data.limit_skills })}
        </p>
      )}
      {data && data.own.length === 0 && <p className="text-sm text-muted">{t("skills.none")}</p>}
      <ul aria-label={t("skills.own")} className="flex flex-col gap-2">
        {(data?.own ?? []).map((skill) => (
          <SkillEntry
            key={skill.id}
            skill={shown(skill)}
            onToggle={(on) => void toggle(skill, on)}
            onOpen={() => setOpen(skill)}
            onTrust={() => setTrusting(skill)}
            onDelete={() => setDeleting(skill)}
          />
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={BUTTON} onClick={() => setCreating(true)} disabled={!data}>
          <Plus className="size-[18px]" aria-hidden="true" />
          {t("skills.create")}
        </button>
        <label id={uploadLabel} className={`${BUTTON} cursor-pointer`}>
          <Upload className="size-[18px]" aria-hidden="true" />
          {t("skills.upload")}
          <input
            ref={upload}
            type="file"
            accept=".zip,.skill"
            aria-labelledby={uploadLabel}
            className="sr-only"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void change(async () => uploadSkill(file));
            }}
          />
        </label>
      </div>
      <ImportForm onImported={refresh} />

      {creating && <CreateDialog onClose={() => setCreating(false)} onSaved={refresh} />}
      {open && <SkillDialog key={open.id ?? open.name} skill={open} onClose={() => setOpen(null)} onSaved={refresh} />}
      {trusting && <TrustDialog skill={trusting} onClose={() => setTrusting(null)} onTrusted={refresh} />}
      {deleting && (
        <Dialog.Root open onOpenChange={(isOpen) => !isOpen && setDeleting(null)}>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
            <Dialog.Content role="alertdialog" className={DIALOG}>
              <Dialog.Title className="mb-2 text-lg font-bold">{t("skills.deleteTitle", { name: deleting.name })}</Dialog.Title>
              <Dialog.Description className="text-sm text-muted">{t("skills.deleteBody")}</Dialog.Description>
              <div className="mt-[18px] flex flex-wrap justify-end gap-2">
                <Dialog.Close className={BUTTON}>{t("skills.cancel")}</Dialog.Close>
                <button
                  type="button"
                  className={DANGER}
                  onClick={() => {
                    const id = deleting.id;
                    setDeleting(null);
                    if (id) void change(async () => unwrap(await api.DELETE("/me/skills/{skill_id}", { params: { path: { skill_id: id } } })));
                  }}
                >
                  {t("skills.delete")}
                </button>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      )}
    </section>
  );
}

function problemText(t: (key: string) => string, failure: unknown): string {
  if (failure instanceof ApiError) {
    const detail = typeof failure.problem.detail === "string" ? failure.problem.detail : "";
    if (failure.code === "resource.conflict") return t("skills.nameTaken");
    if (failure.code === "skill.too_large") return detail || t("skills.tooLarge");
    if (failure.code === "skill.invalid" || failure.code === "skill.import_failed") return detail || t("skills.invalid");
  }
  return t("assistant.notSaved");
}

/** Where a skill came from, in a few words (AGT-025). */
function Origin({ skill }: { skill: Skill }) {
  const { t } = useTranslation();
  if (skill.origin === "builtin") return <>{t("skills.fromInstance")}</>;
  if (skill.origin === "user") return <>{t("skills.byYou")}</>;
  if (skill.origin === "upload") return <>{t("skills.uploaded")}</>;
  if (skill.origin === "import") return <>{t("skills.imported", { url: skill.source_url ?? "" })}</>;
  const conversation = skill.conversation;
  if (!conversation || conversation.deleted) return <>{t("skills.savedInDeletedChat")}</>;
  return (
    <>
      {t("skills.savedInChat")}{" "}
      <Link to={`/c/${conversation.id}`} className="font-semibold text-fg underline underline-offset-2">
        {conversation.title || t("memory.untitledChat")}
      </Link>
    </>
  );
}

function SkillEntry({ skill, onToggle, onOpen, onTrust, onDelete }: { skill: Skill; onToggle: (on: boolean) => void; onOpen: () => void; onTrust?: () => void; onDelete?: () => void }) {
  const { t } = useTranslation();
  return (
    <li className={`flex flex-col gap-2 rounded-2xl border bg-surface px-4 py-3 ${skill.untrusted ? "border-danger/50" : "border-line"}`}>
      <div className="relative flex items-start justify-between gap-3">
        <span className="flex min-w-0 flex-col">
          <b className="font-mono text-[14px] break-all">{skill.name}</b>
          <span className="text-sm break-words text-muted">{skill.description}</span>
        </span>
        <span className="relative mt-1 flex-none">
          <input type="checkbox" role="switch" aria-label={skill.name} checked={skill.enabled} onChange={(event) => onToggle(event.target.checked)} className="peer absolute inset-0 size-full cursor-pointer opacity-0" />
          <span aria-hidden="true" className={`${SWITCH} pointer-events-none block`} />
        </span>
      </div>
      {skill.untrusted && (
        <p className="flex items-start gap-1.5 text-[13px] text-danger">
          <ShieldAlert className="mt-px size-4 flex-none" aria-hidden="true" />
          <span>
            <b>{t("skills.untrusted")}</b> {t("skills.untrustedHint")}
          </span>
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <p className="min-w-0 flex-1 text-[13px] break-words text-muted">
          <Origin skill={skill} />
        </p>
        <button type="button" className={SMALL} onClick={onOpen} aria-label={t("skills.openLabel", { name: skill.name })}>
          {t("skills.open")}
        </button>
        {skill.id !== null && (
          <a className={SMALL} href={`${API_BASE}/me/skills/${skill.id}/archive`} download aria-label={t("skills.downloadLabel", { name: skill.name })}>
            <Download className="size-3.5" aria-hidden="true" />
            {t("skills.download")}
          </a>
        )}
        {skill.untrusted && onTrust && (
          <button type="button" className={SMALL} onClick={onTrust} aria-label={t("skills.trustLabel", { name: skill.name })}>
            {t("skills.trust")}
          </button>
        )}
        {onDelete && (
          <button type="button" className={SMALL} onClick={onDelete} aria-label={t("skills.deleteLabel", { name: skill.name })}>
            {t("skills.delete")}
          </button>
        )}
      </div>
    </li>
  );
}

/** A new skill from a SKILL.md written here: the user's, and trusted. */
function CreateDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => Promise<void> }) {
  const { t } = useTranslation();
  const field = useId();
  const [value, setValue] = useState(NEW_SKILL);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      unwrap(await api.POST("/me/skills", { body: { skill_md: value } }));
      await onSaved();
      onClose();
    } catch (failure) {
      setError(problemText(t, failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className={DIALOG}>
          <Dialog.Title className="mb-2 flex items-center gap-2 text-lg font-bold">
            <Sparkles className="size-5 text-accent" aria-hidden="true" />
            {t("skills.newTitle")}
          </Dialog.Title>
          <Dialog.Description className="text-sm text-muted">{t("skills.newHint")}</Dialog.Description>
          <form onSubmit={(event) => void save(event)} className="mt-3.5 flex min-h-0 flex-col gap-3.5">
            <label htmlFor={field} className="flex min-h-0 flex-col gap-1.5">
              <span className="text-[13.5px] font-semibold">{t("skills.skillMd")}</span>
              <textarea id={field} required maxLength={100000} value={value} onChange={(event) => setValue(event.target.value)} className={TEXTAREA} />
            </label>
            {error && (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Dialog.Close className={BUTTON}>{t("skills.cancel")}</Dialog.Close>
              <button type="submit" className={PRIMARY} disabled={busy || value.trim() === ""}>
                {t("skills.save")}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** A skill's files; the user's text files edited here, SKILL.md first. Editing does not make it trusted (AGT-025). */
function SkillDialog({ skill, onClose, onSaved }: { skill: Skill; onClose: () => void; onSaved: () => Promise<void> }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const field = useId();
  const newPath = useId();
  const editable = skill.id !== null;
  const detail = useQueryDetail(skill);
  const [path, setPath] = useState("SKILL.md");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [adding, setAdding] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const files = detail.data?.files ?? [];
  const file = files.find((item) => item.path === path);
  const value = drafts[path] ?? file?.text ?? (file ? null : "");

  async function save() {
    if (skill.id === null || value === null) return;
    setBusy(true);
    setError(null);
    try {
      const updated = unwrap(await api.PUT("/me/skills/{skill_id}/file", { params: { path: { skill_id: skill.id }, query: { path } }, body: { text: value, executable: file?.executable ?? false } }));
      queries.setQueryData(["me", "skills", skill.id], updated);
      setDrafts((old) => Object.fromEntries(Object.entries(old).filter(([key]) => key !== path)));
      await onSaved();
    } catch (failure) {
      setError(problemText(t, failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className={DIALOG}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <Dialog.Title className="font-mono text-lg font-bold break-all">{skill.name}</Dialog.Title>
              <Dialog.Description className="text-sm text-muted">{editable ? t("skills.editHint") : t("skills.builtinHint")}</Dialog.Description>
            </div>
            <Dialog.Close className="grid size-9 flex-none place-items-center rounded-[10px] text-muted hover:bg-hover hover:text-fg" aria-label={t("skills.close")}>
              <X className="size-5" aria-hidden="true" />
            </Dialog.Close>
          </div>
          <div className="mt-3.5 grid min-h-0 grid-cols-1 gap-3.5 overflow-y-auto sm:grid-cols-[12rem_minmax(0,1fr)]">
            <ul aria-label={t("skills.files")} className="flex flex-col gap-0.5 text-[13px]">
              {files.map((item) => (
                <li key={item.path}>
                  <button
                    type="button"
                    aria-current={item.path === path ? "true" : undefined}
                    onClick={() => setPath(item.path)}
                    className="w-full truncate rounded-lg px-2 py-1 text-left font-mono hover:bg-hover aria-[current=true]:bg-hover aria-[current=true]:font-semibold"
                  >
                    {item.path}
                  </button>
                </li>
              ))}
              {editable && (
                <li className="mt-2 flex flex-col gap-1.5">
                  <label htmlFor={newPath} className="text-[12.5px] text-muted">
                    {t("skills.newFile")}
                  </label>
                  <input id={newPath} className={`${INPUT} h-8 text-[13px]`} value={adding} placeholder={t("skills.pathPlaceholder")} onChange={(event) => setAdding(event.target.value)} />
                  <button
                    type="button"
                    className={SMALL}
                    disabled={adding.trim() === ""}
                    onClick={() => {
                      const next = adding.trim();
                      setDrafts((old) => ({ ...old, [next]: old[next] ?? "" }));
                      setPath(next);
                      setAdding("");
                    }}
                  >
                    {t("skills.addFile")}
                  </button>
                </li>
              )}
            </ul>
            <div className="flex min-w-0 flex-col gap-2">
              {value === null ? (
                <p className="text-sm text-muted">
                  {t("skills.binary")}{" "}
                  <a className="font-semibold text-accent underline" href={fileAddress(skill, path)} download>
                    {t("skills.download")}
                  </a>
                </p>
              ) : (
                <label htmlFor={field} className="flex flex-col gap-1.5">
                  <span className="font-mono text-[13.5px] font-semibold">{path}</span>
                  <textarea id={field} readOnly={!editable} value={value} onChange={(event) => setDrafts((old) => ({ ...old, [path]: event.target.value }))} className={TEXTAREA} />
                </label>
              )}
              {error && (
                <p role="alert" className="text-sm text-danger">
                  {error}
                </p>
              )}
              {editable && value !== null && (
                <div className="flex justify-end">
                  <button type="button" className={PRIMARY} disabled={busy} onClick={() => void save()}>
                    {t("skills.save")}
                  </button>
                </div>
              )}
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function useQueryDetail(skill: Skill) {
  const queries = useQueryClient();
  const key = ["me", "skills", skill.id ?? skill.name];
  const [, force] = useState(0);
  const cached = queries.getQueryData<SkillDetail>(key);
  if (cached === undefined) {
    void queries.fetchQuery({ queryKey: key, queryFn: async () => skillDetail(skill) }).then(() => force((value) => value + 1));
  }
  return { data: cached };
}

/** Marking an untrusted skill trusted, after showing every file it holds (AGT-025). */
function TrustDialog({ skill, onClose, onTrusted }: { skill: Skill; onClose: () => void; onTrusted: () => Promise<void> }) {
  const { t } = useTranslation();
  const detail = useQueryDetail(skill);
  const [busy, setBusy] = useState(false);
  const notify = useNotify();

  async function trust() {
    if (skill.id === null) return;
    setBusy(true);
    try {
      unwrap(await api.PATCH("/me/skills/{skill_id}", { params: { path: { skill_id: skill.id } }, body: { untrusted: false } }));
      await onTrusted();
      onClose();
    } catch (failure) {
      notify({ kind: "error", title: t("skills.notSaved"), text: problemText(t, failure) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className={DIALOG}>
          <Dialog.Title className="mb-2 text-lg font-bold break-all">{t("skills.trustTitle", { name: skill.name })}</Dialog.Title>
          <Dialog.Description className="text-sm text-muted">{t("skills.trustHint")}</Dialog.Description>
          <div className="mt-3.5 flex min-h-0 flex-col gap-3 overflow-y-auto">
            {(detail.data?.files ?? []).map((file) => (
              <section key={file.path} aria-label={file.path} className="rounded-[12px] border border-line">
                <h3 className="border-b border-line px-3 py-1.5 font-mono text-[13px] font-semibold">
                  {file.path}
                  {file.executable && <span className="ml-2 text-[12px] font-normal text-muted">{t("skills.executable")}</span>}
                </h3>
                {file.text === null ? (
                  <p className="px-3 py-2 text-[13px] text-muted">{t("skills.binary")}</p>
                ) : (
                  <pre className="max-h-64 overflow-auto px-3 py-2 font-mono text-[12.5px] whitespace-pre-wrap">{file.text}</pre>
                )}
              </section>
            ))}
          </div>
          <div className="mt-[18px] flex flex-wrap justify-end gap-2">
            <Dialog.Close className={BUTTON}>{t("skills.cancel")}</Dialog.Close>
            <button type="button" className={PRIMARY} disabled={busy || !detail.data} onClick={() => void trust()}>
              {t("skills.trust")}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** Importing from a GitHub repository or folder, or an archive's address, choosing among the skills found. */
function ImportForm({ onImported }: { onImported: () => Promise<void> }) {
  const { t } = useTranslation();
  const field = useId();
  const notify = useNotify();
  const [url, setUrl] = useState("");
  const [found, setFound] = useState<Found[] | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  async function run(event: FormEvent<HTMLFormElement> | null, names?: string[]) {
    event?.preventDefault();
    setBusy(true);
    try {
      const result = unwrap(await api.POST("/me/skills/import", { body: names ? { url, names } : { url } }));
      if (result.imported.length > 0) {
        notify({ kind: "info", title: t("skills.importedCount", { count: result.imported.length }) });
        setFound(null);
        setChosen([]);
        setUrl("");
      } else {
        setFound(result.found);
      }
      await onImported();
    } catch (failure) {
      notify({ kind: "error", title: t("skills.importFailed"), text: problemText(t, failure) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void run(event)} className="flex flex-col gap-2 rounded-2xl border border-line p-3.5">
      <label htmlFor={field} className="text-sm font-bold">
        {t("skills.importLabel")}
      </label>
      <p className="max-w-[62ch] text-[13px] text-muted">{t("skills.importHint")}</p>
      <div className="flex flex-wrap gap-2">
        <input id={field} className={`${INPUT} min-w-0 flex-1`} value={url} placeholder={t("skills.urlPlaceholder")} onChange={(event) => setUrl(event.target.value)} required />
        <button type="submit" className={PRIMARY} disabled={busy || url.trim() === ""}>
          {t("skills.import")}
        </button>
      </div>
      {found !== null && (
        <fieldset className="flex flex-col gap-1.5">
          <legend className="mb-1 text-[13px] font-semibold">{t("skills.choose")}</legend>
          {found.map((item) => (
            <label key={item.name} className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                disabled={!item.valid}
                checked={chosen.includes(item.name)}
                onChange={(event) => setChosen((old) => (event.target.checked ? [...old, item.name] : old.filter((name) => name !== item.name)))}
                className="mt-1"
              />
              <span className="min-w-0">
                <b className="font-mono">{item.name}</b> <span className="text-muted">{item.valid ? item.description : item.problem}</span>
              </span>
            </label>
          ))}
          <div>
            <button type="button" className={BUTTON} disabled={busy || chosen.length === 0} onClick={() => void run(null, chosen)}>
              {t("skills.importChosen")}
            </button>
          </div>
        </fieldset>
      )}
    </form>
  );
}
