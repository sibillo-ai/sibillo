// The user's tool activity, and each user's tool permissions for the household's admins (UX-023, AGT-002, AGT-008, ADR-0090).
import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { api, unwrap, type AuditEvent, type CapabilityClass, type PermissionSetting, type ToolInfo, type ToolName, type ToolPermissions } from "../api/client";
import { useHouseholdMcpServers } from "../mcp";
import { useNotify } from "../notices";
import { outcomeLabel, toolLabel, useTools } from "../tools";
import { Badge, Button, Card, Checkbox, EmptyState, Group, Page, Row, Select } from "../ui";
import { UserEgressSwitch } from "./EgressSettings";

const CLASSES: CapabilityClass[] = ["reads_private_data", "ingests_untrusted", "external_communication", "irreversible", "physical"];
const SETTINGS: PermissionSetting[] = ["allow", "ask", "deny"];
const STRICTNESS: Record<PermissionSetting, number> = { allow: 0, ask: 1, deny: 2 };

/** Every tool call the user's assistant made, newest first, without its content (UX-023, AGT-008). */
export function ActivitySection() {
  const { t, i18n } = useTranslation();
  const toolField = useId();
  const tools = useTools();
  const [tool, setTool] = useState("");
  const activity = useQuery({
    queryKey: ["me", "activity", tool],
    queryFn: async () => unwrap(await api.GET("/me/activity", { params: { query: tool ? { tool, limit: 100 } : { limit: 100 } } })).items,
  });
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  return (
    <Page title={t("activity.page.title")} description={t("activity.page.hint")}>
      <Card rows>
        <Row wide title={t("activity.page.tool")} htmlFor={toolField}>
          <Select id={toolField} value={tool} onChange={(event) => setTool(event.target.value)}>
            <option value="">{t("activity.page.allTools")}</option>
            {(tools.data ?? []).map((item) => (
              <option key={item.name} value={item.name}>
                {toolLabel(t, item.name)}
              </option>
            ))}
          </Select>
        </Row>
        {activity.data && activity.data.length === 0 && <EmptyState icon={<Activity />} title={t("activity.page.none")} />}
        {activity.data && activity.data.length > 0 && (
          <ul aria-label={t("activity.page.calls")} className="divide-y divide-line">
            {activity.data.map((event) => (
              <ActivityItem key={event.id} event={event} when={time.format(new Date(event.created_at))} />
            ))}
          </ul>
        )}
      </Card>
    </Page>
  );
}

function ActivityItem({ event, when }: { event: AuditEvent; when: string }) {
  const { t } = useTranslation();
  const failed = event.outcome === "denied" || event.outcome === "expired" || event.outcome === "refused";
  return (
    <li>
      <Row
        title={
          <>
            {toolLabel(t, event.tool)}
            <Badge tone={failed ? "danger" : "neutral"}>{outcomeLabel(t, event.outcome, event.scope)}</Badge>
            {event.repeated && <Badge tone="warn">{t("activity.page.repeated")}</Badge>}
          </>
        }
        description={
          event.conversation_title === null ? (
            t("activity.page.deletedChat")
          ) : (
            <Link to={`/c/${event.conversation_id}`} className="underline underline-offset-2 hover:text-ink">
              {event.conversation_title || t("activity.page.untitled")}
            </Link>
          )
        }
      >
        <span className="flex-none text-caption text-ink-2 tabular-nums">{when}</span>
      </Row>
    </li>
  );
}

/** What applies to a tool with these settings: its own, else the strictest of its classes', else its default (AGT-002). */
function applied(tool: ToolInfo, permissions: ToolPermissions): { setting: PermissionSetting; from: string | null } {
  const own = permissions.tools[tool.name];
  if (own) return { setting: own, from: tool.name };
  let found: { setting: PermissionSetting; from: string | null } | null = null;
  for (const name of tool.classes) {
    const setting = permissions.classes[name];
    if (setting && (found === null || STRICTNESS[setting] > STRICTNESS[found.setting])) found = { setting, from: name };
  }
  return found ?? { setting: tool.approval_default, from: null };
}

/** Each user's tool permissions, per tool and per capability class, for the household's admins (UX-023, AGT-002). */
export function ToolPermissionsSection() {
  const { t } = useTranslation();
  const userField = useId();
  const users = useQuery({ queryKey: ["tenant", "users"], queryFn: async () => unwrap(await api.GET("/tenant/users", { params: { query: { limit: 100 } } })).items });
  const [userId, setUserId] = useState("");
  return (
    <Page title={t("permissions.title")} description={t("permissions.hint")}>
      <Card rows>
        <Row wide title={t("permissions.user")} htmlFor={userField}>
          <Select id={userField} value={userId} onChange={(event) => setUserId(event.target.value)}>
            <option value="">{t("permissions.chooseUser")}</option>
            {(users.data ?? []).map((user) => (
              <option key={user.id} value={user.id}>
                {user.username}
              </option>
            ))}
          </Select>
        </Row>
        {userId && <UserEgressSwitch key={`egress-${userId}`} userId={userId} />}
      </Card>
      {userId && <PermissionsLoader key={userId} userId={userId} />}
    </Page>
  );
}

function PermissionsLoader({ userId }: { userId: string }) {
  const stored = useQuery({
    queryKey: ["tenant", "users", userId, "tool-permissions"],
    queryFn: async () => unwrap(await api.GET("/tenant/users/{user_id}/tool-permissions", { params: { path: { user_id: userId } } })),
  });
  const tools = useTools();
  if (!stored.data || !tools.data) return null;
  return <PermissionsForm userId={userId} stored={stored.data} tools={tools.data} />;
}

/** A row whose select sets a tool or a capability class: the default, or one of the settings. */
function SettingRow({
  label,
  description,
  value,
  onChange,
}: {
  label: string;
  description?: React.ReactNode;
  value: PermissionSetting | undefined;
  onChange: (value: PermissionSetting | undefined) => void;
}) {
  const { t } = useTranslation();
  const field = useId();
  return (
    <Row wide title={label} htmlFor={field} description={description}>
      <Select id={field} value={value ?? "default"} onChange={(event) => onChange(event.target.value === "default" ? undefined : (event.target.value as PermissionSetting))}>
        <option value="default">{t("permissions.settings.default")}</option>
        {SETTINGS.map((setting) => (
          <option key={setting} value={setting}>
            {t(`permissions.settings.${setting}`)}
          </option>
        ))}
      </Select>
    </Row>
  );
}

function PermissionsForm({ userId, stored, tools }: { userId: string; stored: ToolPermissions; tools: ToolInfo[] }) {
  const { t } = useTranslation();
  const notify = useNotify();
  const [permissions, setPermissions] = useState<ToolPermissions>(stored);
  const [saved, setSaved] = useState(false);

  function setTool(name: ToolName, value: PermissionSetting | undefined) {
    const next = { ...permissions.tools };
    if (value) next[name] = value;
    else delete next[name];
    setPermissions({ ...permissions, tools: next });
    setSaved(false);
  }

  function setClass(name: CapabilityClass, value: PermissionSetting | undefined) {
    const next = { ...permissions.classes };
    if (value) next[name] = value;
    else delete next[name];
    setPermissions({ ...permissions, classes: next });
    setSaved(false);
  }

  function setServer(id: string, denied: boolean) {
    const next = { ...(permissions.servers ?? {}) };
    if (denied) next[id] = "deny";
    else delete next[id];
    setPermissions({ ...permissions, servers: next });
    setSaved(false);
  }

  async function save() {
    try {
      unwrap(await api.PUT("/tenant/users/{user_id}/tool-permissions", { params: { path: { user_id: userId } }, body: permissions }));
      setSaved(true);
    } catch {
      notify({ kind: "error", title: t("errors.title"), text: t("assistant.notSaved") });
    }
  }

  return (
    <>
      <Group title={t("permissions.byClass")} description={t("permissions.byClassHint")}>
        <Card rows>
          {CLASSES.map((name) => (
            <SettingRow key={name} label={t(`permissions.classes.${name}`)} value={permissions.classes[name]} onChange={(value) => setClass(name, value)} />
          ))}
        </Card>
      </Group>
      <Group title={t("permissions.byTool")}>
        <Card>
          {/* A table of one column, so that each tool stays a row by its name: what applies to it, and why, is under the name. */}
          <div role="table" aria-label={t("permissions.byTool")} className="divide-y divide-line">
            {tools.map((tool) => {
              const result = applied(tool, permissions);
              return (
                <div key={tool.name} role="row">
                  <div role="cell">
                    <SettingRow
                      label={toolLabel(t, tool.name)}
                      description={
                        <>
                          <code className="font-mono">{tool.name}</code>
                          {" · "}
                          {t("permissions.applies")} {t(`permissions.settings.${result.setting}`)}
                          {" · "}
                          {result.from === null ? t("permissions.fromDefault") : result.from === tool.name ? t("permissions.fromTool") : t("permissions.fromClass", { name: t(`permissions.classes.${result.from}`) })}
                        </>
                      }
                      value={permissions.tools[tool.name]}
                      onChange={(value) => setTool(tool.name, value)}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      </Group>
      <ServerPermissions denied={permissions.servers ?? {}} onChange={setServer} />
      <div className="flex items-center gap-3">
        <Button variant="primary" onClick={() => void save()}>
          {t("permissions.save")}
        </Button>
        <span role="status" className="text-small text-ink-2">
          {saved ? t("settings.saved") : ""}
        </span>
      </div>
    </>
  );
}

/** The household's remote MCP servers, each of which the admin can deny the user (AGT-029, ADR-0099). */
function ServerPermissions({ denied, onChange }: { denied: Record<string, "deny">; onChange: (id: string, denied: boolean) => void }) {
  const { t } = useTranslation();
  const servers = useHouseholdMcpServers();
  if (!servers.data || servers.data.length === 0) return null;
  return (
    <Group title={t("mcp.permissions.title")} description={t("mcp.permissions.hint")}>
      <Card rows>
        {servers.data.map((server) => (
          <ServerRow key={server.id} name={server.name} denied={denied[server.id] === "deny"} onChange={(on) => onChange(server.id, on)} />
        ))}
      </Card>
    </Group>
  );
}

/** One server: its name, and the box that denies it, named by both. */
function ServerRow({ name, denied, onChange }: { name: string; denied: boolean; onChange: (denied: boolean) => void }) {
  const { t } = useTranslation();
  const title = useId();
  const field = useId();
  const word = useId();
  return (
    <Row title={<span id={title}>{name}</span>}>
      <label htmlFor={field} className="flex flex-none cursor-pointer items-center gap-2 text-small">
        <Checkbox id={field} aria-labelledby={`${title} ${word}`} checked={denied} onChange={(event) => onChange(event.target.checked)} />
        <span id={word}>{t("mcp.permissions.deny")}</span>
      </label>
    </Row>
  );
}
