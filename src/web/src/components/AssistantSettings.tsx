// The settings of conversations: the user's defaults and one conversation's own (CNV-013, CNV-014, I18N-003,
// ADR-0081, ADR-0103).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, ShieldCheck, Sparkles } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, unwrap, type Allowances, type Conversation, type ModelChoice, type Reasoning, type ToolName, type UserSettings, type UserSettingsView } from "../api/client";
import { updateConversation } from "../conversations";
import { languageOptions } from "../languages";
import { findModel, useModels } from "../models";
import { skillsOn, useSkills } from "../skills";
import { useMcpServers } from "../mcp";
import { useBusy } from "../busy";
import { useNotify } from "../notices";
import { toolLabel, useLockedTools } from "../tools";
import { Button, Card, Dialog, EmptyState, Group, Loading, Page, Row, Segmented, Select, Switch as Toggle, TextArea } from "../ui";
import { OwnEgressSwitch } from "./EgressSettings";
import { ServerSwitches } from "./McpSettings";
import { ModelSelect } from "./ModelPicker";

export const SETTINGS = ["me", "settings"] as const;
const REASONING: Reasoning[] = ["off", "on", "deep"];
// Every tool of the assistant, by group (CNV-013, ADR-0087); the groups are the client's own.
const TOOL_GROUPS: { id: string; tools: ToolName[] }[] = [
  { id: "web", tools: ["web_search", "read_page"] },
  { id: "commands", tools: ["run_command", "start_command", "check_command", "stop_command"] },
  { id: "files", tools: ["read_file", "write_file", "edit_file", "create_directory", "list_directory", "find_files", "search_files", "file_info", "view_image"] },
  { id: "showing", tools: ["offer_download"] },
  { id: "questions", tools: ["ask_user_question"] },
  { id: "tasks", tools: ["write_plan", "read_plan", "add_task", "update_task_status", "update_task_statuses", "remove_task"] },
  { id: "memory", tools: ["remember", "update_memory", "forget"] },
  { id: "skills", tools: ["save_skill"] },
  // Proposing a task that runs on its own (TSK-006, ADR-0106).
  { id: "scheduled", tools: ["propose_task", "update_task", "list_tasks"] },
  // Searching and reading the user's other chats (AGT-032, AGT-033, ADR-0107).
  { id: "conversations", tools: ["search_conversations", "read_conversation"] },
];
export function useSettings() {
  return useQuery({ queryKey: SETTINGS, queryFn: async () => unwrap(await api.GET("/me/settings")) });
}

/** Whether a model may reason: not one known not to. */
function useReasons(choice: ModelChoice | null | undefined): boolean {
  const models = useModels();
  return findModel(models.data?.items, choice)?.reasoning !== false;
}

/** A text left as the one it inherits is no text of its own, so it keeps following its default (ADR-0081). */
function own(text: string, inherited: string): string | null {
  return text === inherited ? null : text;
}

/** The preferred language: none, or one of the common languages, each named by the platform (I18N-003, ADR-0103). */
function LanguageField({ value, onChange }: { value: string | null; onChange: (language: string | null) => void }) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const hint = useId();
  return (
    <Row title={t("assistant.language")} description={<span id={hint}>{t("assistant.languageHint")}</span>} htmlFor={id} wide>
      <Select id={id} aria-describedby={hint} value={value ?? ""} onChange={(event) => onChange(event.target.value || null)}>
        <option value="">{t("assistant.languageOfMessages")}</option>
        {languageOptions(i18n.language, value).map((option) => (
          <option key={option.tag} value={option.tag} lang={option.tag}>
            {option.label}
          </option>
        ))}
      </Select>
    </Row>
  );
}

/** A row: the levels of reasoning, all off for a model that cannot reason, with a note that says so (CNV-013). */
function ReasoningField({ value, onChange, reasons }: { value: Reasoning; onChange: (value: Reasoning) => void; reasons: boolean }) {
  const { t } = useTranslation();
  const label = useId();
  const note = useId();
  return (
    <Row
      wide
      title={<span id={label}>{t("assistant.reasoning")}</span>}
      description={
        <>
          {t("assistant.reasoningHint")}
          {!reasons && (
            <span id={note} className="block">
              {t("assistant.cannotReason")}
            </span>
          )}
        </>
      }
    >
      <Segmented
        labelledBy={label}
        {...(reasons ? {} : { describedBy: note })}
        options={REASONING.map((level) => ({ value: level, label: t(`assistant.levels.${level}`) }))}
        value={reasons ? value : "off"}
        onChange={onChange}
        disabled={!reasons}
      />
    </Row>
  );
}

/** A switch, as a row of a card: the label names it, the description says more (UX-007). */
export function Switch({
  label,
  description,
  checked,
  onChange,
  locked = false,
}: {
  label: string;
  description?: React.ReactNode;
  checked: boolean;
  onChange: (on: boolean) => void;
  /** Kept for its callers: every row's title has the same weight (ADR-0111). */
  strong?: boolean;
  locked?: boolean;
}) {
  const name = useId();
  const more = useId();
  return (
    <Row title={label} description={description ? <span id={more}>{description}</span> : undefined} htmlFor={name}>
      <Toggle id={name} checked={checked} disabled={locked} aria-describedby={description ? more : undefined} onChange={onChange} />
    </Row>
  );
}

/**
 * Every tool, by group with its name, each with a switch, and a switch for each group (CNV-013, ADR-0087).
 * A tool the household's admin denied is off and locked, and says why (ADR-0090).
 * After them, what else is switched with the tools: the household's servers (AGT-029).
 */
function ToolSwitches({ disabled, onChange, children }: { disabled: ToolName[]; onChange: (disabled: ToolName[]) => void; children?: React.ReactNode }) {
  const { t } = useTranslation();
  const locked = useLockedTools();
  const isOn = (tool: ToolName) => !disabled.includes(tool) && !locked.has(tool);
  const set = (tools: ToolName[], on: boolean) => onChange(on ? disabled.filter((name) => !tools.includes(name)) : [...disabled.filter((name) => !tools.includes(name)), ...tools]);
  return (
    <Group role="group" title={t("assistant.tools")} description={t("assistant.toolsHint")}>
      {TOOL_GROUPS.map((group) => {
        const on = group.tools.filter(isOn).length;
        const free = group.tools.filter((tool) => !locked.has(tool));
        return (
          <Card key={group.id} rows>
            <Switch
              label={t(`assistant.toolGroups.${group.id}`)}
              description={t("assistant.toolsOn", { on, total: group.tools.length })}
              checked={free.length > 0 && free.every(isOn)}
              onChange={(checked) => set(free, checked)}
              locked={free.length === 0}
            />
            {group.tools.map((tool) => (
              <Switch
                key={tool}
                label={t(`assistant.toolNames.${tool}`)}
                description={
                  <>
                    <code className="font-mono">{tool}</code>
                    {locked.has(tool) && <span className="block">{t("permissions.lockedByAdmin")}</span>}
                  </>
                }
                checked={isOn(tool)}
                locked={locked.has(tool)}
                onChange={(checked) => set([tool], checked)}
              />
            ))}
          </Card>
        );
      })}
      {children}
    </Group>
  );
}

/** The switches of the household's servers, in a card of their own; nothing without a server (AGT-029). */
function Servers({ off, onChange }: { off: string[]; onChange: (off: string[]) => void }) {
  const { t } = useTranslation();
  const servers = useMcpServers();
  if (!servers.data || servers.data.length === 0) return null;
  return (
    <Group role="group" title={t("mcp.switches.title")} description={t("mcp.switches.hint")}>
      <Card rows>
        <ServerSwitches off={off} onChange={onChange} />
      </Card>
    </Group>
  );
}

/** A row: the prompt added to the system prompt. */
function AdditionalPrompt({ value, onChange, placeholder }: { value: string; onChange: (text: string) => void; placeholder: string }) {
  const { t } = useTranslation();
  const id = useId();
  return (
    <Row
      title={t("assistant.additional")}
      description={t("assistant.additionalHint")}
      htmlFor={id}
      below={<TextArea id={id} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} maxLength={20000} />}
    />
  );
}

/** The system prompt, set apart: replacing it changes who the assistant is (CNV-014). */
function DangerZone({ value, inherited, onChange }: { value: string; inherited: string; onChange: (text: string) => void }) {
  const { t } = useTranslation();
  const id = useId();
  return (
    <Group role="region" title={t("assistant.dangerZone")} description={t("assistant.dangerHint")}>
      <Card rows>
        <Row
          title={t("assistant.base")}
          description={t("assistant.baseHint")}
          htmlFor={id}
          below={<TextArea id={id} tall value={value} onChange={(event) => onChange(event.target.value)} maxLength={20000} />}
        >
          <Button size="sm" disabled={value === inherited} onClick={() => onChange(inherited)}>
            <RotateCcw aria-hidden="true" />
            {/* Named in its content, so that the field's label stays the only one that names it. */}
            <span aria-hidden="true">{t("assistant.restoreShort")}</span>
            <span className="sr-only">{t("assistant.restore")}</span>
          </Button>
        </Row>
      </Card>
    </Group>
  );
}

/** The user's defaults, in the settings: settings save at once, prompts on request. */
export function AssistantSection() {
  const settings = useSettings();
  if (settings.isPending) return <Loading />;
  if (!settings.data) return null;
  return <AssistantForm view={settings.data} />;
}

function AssistantForm({ view }: { view: UserSettingsView }) {
  const { t } = useTranslation();
  const models = useModels();
  const householdModel = findModel(models.data?.items, models.data?.default);
  const queries = useQueryClient();
  const notify = useNotify();
  const { built_in_base_instructions: builtIn, ...stored } = view;
  // The form's own copy, so that a choice shows at once.
  const [settings, setSettings] = useState<UserSettings>(stored);
  const reasons = useReasons(settings.model);
  const [base, setBase] = useState(settings.base_instructions ?? builtIn);
  const [additional, setAdditional] = useState(settings.additional_instructions ?? "");
  const [saved, setSaved] = useState(false);
  const { busy, run } = useBusy();

  async function save(changes: Partial<UserSettings>) {
    const body = { ...settings, ...changes };
    setSettings(body);
    try {
      const updated = unwrap(await api.PUT("/me/settings", { body }));
      queries.setQueryData(SETTINGS, updated);
      return true;
    } catch {
      setSettings(settings);
      notify({ kind: "error", title: t("errors.title"), text: t("assistant.notSaved") });
      return false;
    }
  }

  async function savePrompts() {
    setSaved(await save({ base_instructions: own(base, builtIn), additional_instructions: own(additional, "") }));
  }

  return (
    <Page title={t("assistant.title")} description={t("assistant.hint")}>
      <Card rows>
        <Row title={t("assistant.model")} description={t("assistant.modelHint")} wide>
          <ModelSelect
            value={settings.model}
            onChange={(model) => void save({ model })}
            label={t("assistant.model")}
            placeholder={householdModel ? t("assistant.householdModel", { name: householdModel.name }) : t("assistant.noHouseholdModel")}
          />
        </Row>
        <OwnEgressSwitch />
        <LanguageField value={settings.language ?? null} onChange={(language) => void save({ language })} />
        <ReasoningField value={settings.reasoning ?? "on"} onChange={(reasoning) => void save({ reasoning })} reasons={reasons} />
      </Card>
      <ToolSwitches disabled={settings.disabled_tools} onChange={(disabled_tools) => void save({ disabled_tools })}>
        <Servers off={settings.disabled_servers ?? []} onChange={(disabled_servers) => void save({ disabled_servers })} />
      </ToolSwitches>
      <Card rows>
        <AdditionalPrompt
          value={additional}
          onChange={(text) => {
            setAdditional(text);
            setSaved(false);
          }}
          placeholder={t("assistant.none")}
        />
      </Card>
      <DangerZone
        value={base}
        inherited={builtIn}
        onChange={(text) => {
          setBase(text);
          setSaved(false);
        }}
      />
      <div className="flex items-center gap-3">
        <Button variant="primary" busy={busy("prompts")} onClick={() => void run("prompts", savePrompts)}>
          {t("assistant.savePrompts")}
        </Button>
        <span role="status" className="text-small text-ink-2">
          {saved ? t("settings.saved") : ""}
        </span>
      </div>
    </Page>
  );
}

/** One conversation's settings and prompts, in a dialog; they apply from its next answer. */
export function ChatSettings({ conversation, open, onOpenChange }: { conversation: Conversation; open: boolean; onOpenChange: (open: boolean) => void }) {
  if (!open) return null;
  return <ChatSettingsLoader conversation={conversation} onDone={() => onOpenChange(false)} />;
}

/** The dialog's fields start from the user's defaults, so it waits for them. */
function ChatSettingsLoader(props: { conversation: Conversation; onDone: () => void }) {
  const { t } = useTranslation();
  const settings = useSettings();
  if (settings.isPending)
    return (
      <Dialog onClose={props.onDone} title={t("assistant.chat")} description={t("assistant.chatHint")} size="lg">
        <Loading />
      </Dialog>
    );
  if (!settings.data) return null;
  return <ChatSettingsForm {...props} defaults={settings.data} />;
}

function ChatSettingsForm({ conversation, defaults, onDone }: { conversation: Conversation; defaults: UserSettingsView; onDone: () => void }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const reasons = useReasons(conversation.model);
  const inheritedBase = defaults.base_instructions ?? defaults.built_in_base_instructions;
  const inheritedAdditional = defaults.additional_instructions ?? "";
  const [reasoning, setReasoning] = useState(conversation.reasoning);
  const [disabled, setDisabled] = useState(conversation.disabled_tools);
  const [skillsOff, setSkillsOff] = useState(conversation.disabled_skills);
  const [serversOff, setServersOff] = useState(conversation.disabled_servers);
  const [base, setBase] = useState(conversation.base_instructions ?? inheritedBase);
  const [additional, setAdditional] = useState(conversation.additional_instructions ?? inheritedAdditional);
  const [allowances, setAllowances] = useState<Allowances>(conversation.allowances);
  const { busy, run } = useBusy();
  const withdrawn = allowances.web_and_commands !== conversation.allowances.web_and_commands || allowances.tools.length !== conversation.allowances.tools.length;

  async function save() {
    try {
      const updated = await updateConversation(conversation.id, {
        reasoning,
        disabled_tools: disabled,
        disabled_skills: skillsOff,
        disabled_servers: serversOff,
        ...(withdrawn ? { allowances } : {}),
        base_instructions: own(base, inheritedBase),
        additional_instructions: own(additional, inheritedAdditional),
      });
      queries.setQueryData(["conversation", conversation.id, "details"], updated);
      onDone();
    } catch {
      notify({ kind: "error", title: t("errors.title"), text: t("assistant.notSaved") });
    }
  }

  return (
    <Dialog
      onClose={onDone}
      title={t("assistant.chat")}
      description={t("assistant.chatHint")}
      size="lg"
      footer={
        <>
          <Button onClick={onDone}>{t("conversationMenu.cancel")}</Button>
          <Button variant="primary" busy={busy("save")} onClick={() => void run("save", save)}>
            {t("conversationMenu.save")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-6">
        <Card rows>
          <ReasoningField value={reasoning} onChange={setReasoning} reasons={reasons} />
        </Card>
        <ToolSwitches disabled={disabled} onChange={setDisabled}>
          <Servers off={serversOff} onChange={setServersOff} />
        </ToolSwitches>
        <SkillSwitches off={skillsOff} onChange={setSkillsOff} />
        <AllowedInChat allowances={allowances} onChange={setAllowances} />
        <Card rows>
          <AdditionalPrompt value={additional} onChange={setAdditional} placeholder={t("assistant.none")} />
        </Card>
        <DangerZone value={base} inherited={inheritedBase} onChange={setBase} />
      </div>
    </Dialog>
  );
}

/** The skills on for the user, each with a switch for this conversation; a skill added later is on (AGT-017, UX-028). */
function SkillSwitches({ off, onChange }: { off: string[]; onChange: (off: string[]) => void }) {
  const { t } = useTranslation();
  const skills = skillsOn(useSkills().data);
  return (
    <Group role="group" title={t("skills.title")} description={t("skills.chatHint")}>
      <Card rows>
        {skills.length === 0 && (
          <EmptyState icon={<Sparkles />} title={t("skills.noneOn")}>
            {t("skills.noneOnHint")}
          </EmptyState>
        )}
        {skills.map((skill) => (
          <Switch
            key={skill.name}
            label={skill.name}
            description={skill.description}
            checked={!off.includes(skill.name)}
            onChange={(on) => onChange(on ? off.filter((name) => name !== skill.name) : [...off, skill.name])}
          />
        ))}
      </Card>
    </Group>
  );
}

/** What the user allowed in this conversation by answering approval requests, each one withdrawable (AGT-006, UX-023). */
function AllowedInChat({ allowances, onChange }: { allowances: Allowances; onChange: (allowances: Allowances) => void }) {
  const { t } = useTranslation();
  const items: { key: string; label: string; withdraw: () => void }[] = [
    ...(allowances.web_and_commands ? [{ key: "web_and_commands", label: t("approvals.webAndCommands"), withdraw: () => onChange({ ...allowances, web_and_commands: false }) }] : []),
    ...allowances.tools.map((tool) => ({ key: tool, label: toolLabel(t, tool), withdraw: () => onChange({ ...allowances, tools: allowances.tools.filter((name) => name !== tool) }) })),
  ];
  return (
    <Group role="region" title={t("approvals.allowedInChat")} description={t("approvals.allowedHint")}>
      <Card rows>
        {items.length === 0 && (
          <EmptyState icon={<ShieldCheck />} title={t("approvals.nothingAllowed")}>
            {t("approvals.nothingAllowedHint")}
          </EmptyState>
        )}
        {items.map((item) => (
          <Row key={item.key} title={item.label}>
            <Button size="sm" variant="danger" onClick={item.withdraw}>
              {t("approvals.withdraw")}
            </Button>
          </Row>
        ))}
      </Card>
    </Group>
  );
}
