// The Skills page of the user's settings (UX-028, AGT-017, AGT-024, AGT-025, ADR-0096).
import { useQueryClient } from "@tanstack/react-query";
import { Download, Plus, ShieldAlert, Sparkles, Upload } from "lucide-react";
import { type FormEvent, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { API_BASE, ApiError, api, unwrap, type Schemas } from "../api/client";
import { fileAddress, SKILLS, type Skill, type SkillDetail, skillDetail, uploadSkill, useSkills } from "../skills";
import { useNotify } from "../notices";
import { Badge, Button, buttonClass, Card, Checkbox, Dialog, EmptyState, FileInput, FormField, Group, NavItem, Notice, Page, Row, Switch, TextArea, TextInput, Tile } from "../ui";

type Found = Schemas["SkillImport"]["found"][number];

const NEW_SKILL = "---\nname: my-skill\ndescription: Use when …\n---\n\n# My skill\n\nWhat to do, step by step.\n";

/** The built-in skills, then the user's, each with its switch; and creating, uploading and importing them. */
export function SkillsSection() {
  const { t, i18n } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const skills = useSkills();
  const upload = useRef<HTMLInputElement>(null);
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
    <Page title={t("skills.title")} description={t("skills.hint")}>
      <Group title={t("skills.builtin")}>
        {data && (
          <Card>
            <ul aria-label={t("skills.builtin")} className="divide-y divide-line">
              {data.builtin.map((skill) => (
                <SkillEntry key={skill.name} skill={shown(skill)} onToggle={(on) => void toggle(skill, on)} onOpen={() => setOpen(skill)} />
              ))}
            </ul>
          </Card>
        )}
      </Group>

      <Group
        title={t("skills.own")}
        description={
          data && t("skills.used", { used: number.format(data.used_bytes / 1048576), limit: number.format(data.limit_bytes / 1048576), count: data.own.length, most: data.limit_skills })
        }
      >
        {data && (
          <Card>
            {data.own.length === 0 ? (
              <EmptyState icon={<Sparkles />} title={t("skills.none")} />
            ) : (
              <ul aria-label={t("skills.own")} className="divide-y divide-line">
                {data.own.map((skill) => (
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
            )}
          </Card>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => setCreating(true)} disabled={!data}>
            <Plus aria-hidden="true" />
            {t("skills.create")}
          </Button>
          <Button onClick={() => upload.current?.click()}>
            <Upload aria-hidden="true" />
            {t("skills.upload")}
          </Button>
          <FileInput
            ref={upload}
            accept=".zip,.skill"
            aria-label={t("skills.upload")}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void change(async () => uploadSkill(file));
            }}
          />
        </div>
      </Group>
      <ImportForm onImported={refresh} />

      {creating && <CreateDialog onClose={() => setCreating(false)} onSaved={refresh} />}
      {open && <SkillDialog key={open.id ?? open.name} skill={open} onClose={() => setOpen(null)} onSaved={refresh} />}
      {trusting && <TrustDialog skill={trusting} onClose={() => setTrusting(null)} onTrusted={refresh} />}
      {deleting && (
        <Dialog
          asks
          size="sm"
          onClose={() => setDeleting(null)}
          title={t("skills.deleteTitle", { name: deleting.name })}
          description={t("skills.deleteBody")}
          footer={
            <>
              <Button onClick={() => setDeleting(null)}>{t("skills.cancel")}</Button>
              <Button
                variant="danger-solid"
                onClick={() => {
                  const id = deleting.id;
                  setDeleting(null);
                  if (id) void change(async () => unwrap(await api.DELETE("/me/skills/{skill_id}", { params: { path: { skill_id: id } } })));
                }}
              >
                {t("skills.delete")}
              </Button>
            </>
          }
        />
      )}
    </Page>
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
      <Link to={`/c/${conversation.id}`} className="font-semibold text-ink underline underline-offset-2">
        {conversation.title || t("memory.untitledChat")}
      </Link>
    </>
  );
}

function SkillEntry({ skill, onToggle, onOpen, onTrust, onDelete }: { skill: Skill; onToggle: (on: boolean) => void; onOpen: () => void; onTrust?: () => void; onDelete?: () => void }) {
  const { t } = useTranslation();
  return (
    <li>
      <Row
        mono
        title={<span className="min-w-0 break-all">{skill.name}</span>}
        description={skill.description}
        below={
          <>
            {skill.untrusted && (
              <Notice role="note" tone="warn" icon={<ShieldAlert aria-hidden="true" />} title={t("skills.untrusted")}>
                {t("skills.untrustedHint")}
              </Notice>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <p className="min-w-0 flex-1 text-small break-words text-ink-2">
                <Origin skill={skill} />
              </p>
              <Button size="sm" onClick={onOpen} aria-label={t("skills.openLabel", { name: skill.name })}>
                {t("skills.open")}
              </Button>
              {skill.id !== null && (
                <a className={buttonClass({ size: "sm" })} href={`${API_BASE}/me/skills/${skill.id}/archive`} download aria-label={t("skills.downloadLabel", { name: skill.name })}>
                  <Download aria-hidden="true" />
                  {t("skills.download")}
                </a>
              )}
              {skill.untrusted && onTrust && (
                <Button size="sm" onClick={onTrust} aria-label={t("skills.trustLabel", { name: skill.name })}>
                  {t("skills.trust")}
                </Button>
              )}
              {onDelete && (
                <Button size="sm" variant="danger" onClick={onDelete} aria-label={t("skills.deleteLabel", { name: skill.name })}>
                  {t("skills.delete")}
                </Button>
              )}
            </div>
          </>
        }
      >
        <Switch aria-label={skill.name} checked={skill.enabled} onChange={onToggle} />
      </Row>
    </li>
  );
}

/** A new skill from a SKILL.md written here: the user's, and trusted. */
function CreateDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => Promise<void> }) {
  const { t } = useTranslation();
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
    <Dialog
      size="lg"
      onClose={onClose}
      title={t("skills.newTitle")}
      description={t("skills.newHint")}
      leading={
        <Tile>
          <Sparkles />
        </Tile>
      }
      onSubmit={(event) => void save(event)}
      footer={
        <>
          <Button onClick={onClose}>{t("skills.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={busy || value.trim() === ""}>
            {t("skills.save")}
          </Button>
        </>
      }
    >
      <FormField label={t("skills.skillMd")} error={error}>
        {(ties) => <TextArea {...ties} mono tall required maxLength={100000} value={value} onChange={(event) => setValue(event.target.value)} />}
      </FormField>
    </Dialog>
  );
}

/** A skill's files; the user's text files edited here, SKILL.md first. Editing does not make it trusted (AGT-025). */
function SkillDialog({ skill, onClose, onSaved }: { skill: Skill; onClose: () => void; onSaved: () => Promise<void> }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
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
    <Dialog
      size="lg"
      onClose={onClose}
      title={skill.name}
      description={editable ? t("skills.editHint") : t("skills.builtinHint")}
      footer={
        <>
          <Button onClick={onClose}>{t("skills.close")}</Button>
          {editable && value !== null && (
            <Button variant="primary" disabled={busy} onClick={() => void save()}>
              {t("skills.save")}
            </Button>
          )}
        </>
      }
    >
      <div className="flex min-w-0 flex-col gap-4 sm:flex-row">
        <div className="flex flex-col gap-4 sm:w-48 sm:flex-none">
          <ul aria-label={t("skills.files")} className="flex flex-col gap-px">
            {files.map((item) => (
              <li key={item.path}>
                <NavItem current={item.path === path} onClick={() => setPath(item.path)}>
                  {item.path}
                </NavItem>
              </li>
            ))}
          </ul>
          {editable && (
            <div className="flex flex-col gap-2">
              <FormField label={t("skills.newFile")}>
                {(ties) => <TextInput {...ties} mono value={adding} placeholder={t("skills.pathPlaceholder")} onChange={(event) => setAdding(event.target.value)} />}
              </FormField>
              <Button
                size="sm"
                disabled={adding.trim() === ""}
                onClick={() => {
                  const next = adding.trim();
                  setDrafts((old) => ({ ...old, [next]: old[next] ?? "" }));
                  setPath(next);
                  setAdding("");
                }}
              >
                {t("skills.addFile")}
              </Button>
            </div>
          )}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          {value === null ? (
            <p className="text-body text-ink-2">
              {t("skills.binary")}{" "}
              <a className="font-semibold text-ink underline underline-offset-2" href={fileAddress(skill, path)} download>
                {t("skills.download")}
              </a>
            </p>
          ) : (
            <FormField label={path}>{(ties) => <TextArea {...ties} mono tall readOnly={!editable} value={value} onChange={(event) => setDrafts((old) => ({ ...old, [path]: event.target.value }))} />}</FormField>
          )}
          {error && <Notice tone="error">{error}</Notice>}
        </div>
      </div>
    </Dialog>
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
    <Dialog
      size="lg"
      onClose={onClose}
      title={t("skills.trustTitle", { name: skill.name })}
      description={t("skills.trustHint")}
      footer={
        <>
          <Button onClick={onClose}>{t("skills.cancel")}</Button>
          <Button variant="primary" disabled={busy || !detail.data} onClick={() => void trust()}>
            {t("skills.trust")}
          </Button>
        </>
      }
    >
      {(detail.data?.files ?? []).map((file) => (
        <Group key={file.path} role="region" title={file.path} action={file.executable && <Badge>{t("skills.executable")}</Badge>}>
          <Card>
            {file.text === null ? (
              <p className="px-4 py-3 text-small text-ink-2">{t("skills.binary")}</p>
            ) : (
              <pre className="max-h-64 overflow-auto px-4 py-3 font-mono text-small whitespace-pre-wrap">{file.text}</pre>
            )}
          </Card>
        </Group>
      ))}
    </Dialog>
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
    <form onSubmit={(event) => void run(event)}>
      <Card>
        <Row
          title={t("skills.importLabel")}
          description={t("skills.importHint")}
          htmlFor={field}
          below={
            <>
              <div className="flex flex-wrap gap-2">
                <div className="min-w-0 flex-1">
                  <TextInput id={field} value={url} placeholder={t("skills.urlPlaceholder")} onChange={(event) => setUrl(event.target.value)} required />
                </div>
                <Button type="submit" variant="primary" disabled={busy || url.trim() === ""}>
                  {t("skills.import")}
                </Button>
              </div>
              {found !== null && (
                <fieldset className="flex flex-col gap-2">
                  <legend className="mb-2 text-small font-semibold">{t("skills.choose")}</legend>
                  {found.map((item) => (
                    <label key={item.name} className="flex items-start gap-2 text-body">
                      <span className="flex h-5 items-center">
                        <Checkbox
                          disabled={!item.valid}
                          checked={chosen.includes(item.name)}
                          onChange={(event) => setChosen((old) => (event.target.checked ? [...old, item.name] : old.filter((name) => name !== item.name)))}
                        />
                      </span>
                      <span className="min-w-0">
                        <b className="font-mono font-semibold">{item.name}</b> <span className="text-ink-2">{item.valid ? item.description : item.problem}</span>
                      </span>
                    </label>
                  ))}
                  <div>
                    <Button disabled={busy || chosen.length === 0} onClick={() => void run(null, chosen)}>
                      {t("skills.importChosen")}
                    </Button>
                  </div>
                </fieldset>
              )}
            </>
          }
        />
      </Card>
    </form>
  );
}
