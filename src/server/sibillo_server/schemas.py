"""Request and response bodies of the public API (specs/contracts/openapi.yaml)."""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, HttpUrl, PlainSerializer, UrlConstraints

type Role = Literal["member", "tenant_admin"]


class Request(BaseModel):
    """A request body: unknown fields are rejected (`additionalProperties: false`)."""

    model_config = ConfigDict(extra="forbid")


class Response(BaseModel):
    pass


def _rfc3339(value: datetime.datetime) -> str:
    return value.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")


# Timestamps are RFC 3339 in UTC.
type Timestamp = Annotated[datetime.datetime, PlainSerializer(_rfc3339, return_type=str, when_used="json")]


class LoginRequest(Request):
    username: Annotated[str, Field(min_length=1, max_length=64)]
    password: Annotated[str, Field(min_length=1, max_length=1024)]
    device_name: Annotated[str, Field(min_length=1, max_length=100)]
    # `cookie` for browsers: the token is set as an HttpOnly cookie instead (ADR-0067).
    session_delivery: Literal["token", "cookie"] = "token"


class User(Response):
    id: uuid.UUID
    tenant_id: uuid.UUID
    username: str
    display_name: str
    role: Role
    instance_admin: bool
    created_at: Timestamp


class DeviceSession(Response):
    id: uuid.UUID
    device_name: str
    created_at: Timestamp
    last_used_at: Timestamp
    expires_at: Timestamp
    current: bool


class NotificationSettings(Response):
    """Whether notifications are available, and on for the current device session (UX-004, ADR-0101)."""

    available: bool
    subscribed: bool
    # Absent when notifications are unavailable.
    public_key: str | None = None


class NotificationKeys(BaseModel):
    p256dh: Annotated[str, Field(min_length=1, max_length=256)]
    auth: Annotated[str, Field(min_length=1, max_length=64)]


class NotificationSubscription(BaseModel):
    """A browser's push subscription, as `PushSubscription.toJSON()` gives it; other fields are ignored."""

    endpoint: Annotated[str, Field(min_length=1, max_length=2048)]
    keys: NotificationKeys


class LoginResponse(Response):
    # Absent when the session was set as a cookie.
    token: Annotated[str | None, Field(exclude_if=lambda value: value is None)] = None
    session: DeviceSession
    user: User


class DeviceSessionList(Response):
    items: list[DeviceSession]


# Passkeys, a second factor (AUTH-010, ADR-0094). WebAuthn's own JSON forms
# pass through as objects, checked by the WebAuthn library.


class PasskeyRequired(Response):
    sign_in_token: str
    options: dict[str, Any]


class PasskeyLoginRequest(Request):
    sign_in_token: Annotated[str, Field(min_length=1, max_length=256)]
    credential: dict[str, Any]
    device_name: Annotated[str, Field(min_length=1, max_length=100)]
    session_delivery: Literal["token", "cookie"] = "token"


class PasswordConfirmation(Request):
    password: Annotated[str, Field(min_length=1, max_length=1024)]


class PasskeyRegistration(Response):
    registration_id: uuid.UUID
    options: dict[str, Any]


class AddPasskeyRequest(Request):
    registration_id: uuid.UUID
    name: Annotated[str, Field(min_length=1, max_length=100)]
    credential: dict[str, Any]


class Passkey(Response):
    id: uuid.UUID
    name: str
    created_at: Timestamp
    last_used_at: Timestamp | None


class PasskeyList(Response):
    available: bool
    items: list[Passkey]


class PasskeyCount(Response):
    count: int


class UserPage(Response):
    items: list[User]
    next_cursor: str | None


class _NewUser(Request):
    username: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,63}$")]
    display_name: Annotated[str, Field(min_length=1, max_length=100)]
    password: Annotated[str, Field(min_length=12, max_length=1024)]


class CreateUserRequest(_NewUser):
    role: Role


class FirstAdminRequest(_NewUser):
    """The first admin of a new tenant is a tenant admin."""

    role: Literal["tenant_admin"]


class CreateTenantRequest(Request):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    admin: FirstAdminRequest


class Tenant(Response):
    id: uuid.UUID
    name: str
    created_at: Timestamp


class TenantPage(Response):
    items: list[Tenant]
    next_cursor: str | None


type DecimalText = Annotated[str, Field(pattern=r"^[0-9]{1,10}(\.[0-9]{1,10})?$")]


class ModelPricesOut(Response):
    input: str
    # Left out when not set: the contract has no null price.
    cached_input: Annotated[str | None, Field(exclude_if=lambda value: value is None)] = None
    output: str
    currency: str


# A connection reaches OpenRouter or a server with an OpenAI-compatible API (ADR-0057, ADR-0069).
type ConnectionKind = Literal["openrouter", "openai"]
# Where inference runs (MOD-010, ADR-0066).
type Location = Literal["local", "remote"]
type Address = Annotated[HttpUrl, UrlConstraints(max_length=2000)]
type ApiKey = Annotated[str, Field(min_length=1, max_length=1000)]


type ContextWindow = Annotated[int, Field(ge=512, le=10_000_000)]


class CreateConnectionRequest(Request):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    kind: ConnectionKind
    base_url: Address | None = None
    location: Location | None = None
    context_window: ContextWindow | None = None
    api_key: ApiKey | None = None


class UpdateConnectionRequest(Request):
    """Only the fields present change; `api_key` set to null is removed."""

    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    base_url: Address | None = None
    location: Location | None = None
    context_window: ContextWindow | None = None
    api_key: ApiKey | None = None


class Server(Response):
    """The server behind a connection, when Sibillo recognized it (MOD-019, ADR-0093)."""

    product: Literal["ollama"]
    version: str


class Connection(Response):
    id: uuid.UUID
    name: str
    kind: ConnectionKind
    server: Server | None
    base_url: str
    location: Location
    has_api_key: bool
    private_network: bool
    context_window: int | None
    model_count: int
    models_refreshed_at: Timestamp | None
    created_at: Timestamp
    updated_at: Timestamp


class ConnectionList(Response):
    items: list[Connection]


type TestStepName = Literal["resolve", "connect", "tls", "authenticate", "list_models"]
type TestReason = Literal[
    "name_not_found",
    "connection_refused",
    "timeout",
    "tls_untrusted",
    "address_not_allowed",
    "http_error",
    "unauthorized",
    "not_a_model_server",
]


class ConnectionTestStep(Response):
    step: TestStepName
    outcome: Literal["passed", "failed", "skipped"]
    duration_ms: int | None
    detail: str


class ConnectionTest(Response):
    passed: bool
    steps: list[ConnectionTestStep]
    reason: TestReason | None
    http_status: int | None
    technical_detail: str | None
    model_count: int | None


class ModelChoice(Request):
    connection_id: uuid.UUID
    model: Annotated[str, Field(min_length=1, max_length=200)]


class ModelChoiceOut(Response):
    connection_id: uuid.UUID
    model: str


# What a model does: answer in conversations, turn speech into text, or read text aloud (ADR-0088).
type ModelKind = Literal["chat", "transcription", "speech"]


class ModelOption(Response):
    connection_id: uuid.UUID
    connection_name: str
    model: str
    name: str
    location: Location
    prices: ModelPricesOut | None
    context_window: int | None
    # The window the model's server last said it runs the model with (MOD-019, ADR-0093).
    served_context_window: int | None
    tools: bool | None
    reasoning: bool | None
    kind: ModelKind
    voices: list[str] | None


class SpeechChoice(Request):
    """A speech model and the voice it reads with (API-006, ADR-0088)."""

    connection_id: uuid.UUID
    model: Annotated[str, Field(min_length=1, max_length=200)]
    voice: Annotated[str, Field(min_length=1, max_length=200)]


class SpeechSettings(Request):
    """The household's speech models; null when it has none (API-006, ADR-0088)."""

    transcription: ModelChoice | None
    speech: SpeechChoice | None


# A data egress policy: every model, or only local ones (MOD-003, ADR-0091).
type EgressPolicy = Literal["any", "local_only"]


class EgressPolicySetting(Request):
    policy: EgressPolicy


class EgressPolicies(Response):
    """The policies that apply to a user, and the strictest of them, which the gateway enforces."""

    household: EgressPolicy
    admin: EgressPolicy
    own: EgressPolicy
    effective: EgressPolicy


class ModelList(Response):
    items: list[ModelOption]
    default: ModelChoiceOut | None
    speech: SpeechSettings
    egress: EgressPolicies


class Transcription(Response):
    text: str


class SynthesisRequest(Request):
    text: Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]


# How much a model reasons before it answers, and the tools a user can switch off (CNV-013, ADR-0081, ADR-0087).
type Reasoning = Literal["off", "on", "deep"]
type ToolName = Literal[
    "web_search",
    "read_page",
    "run_command",
    "start_command",
    "check_command",
    "stop_command",
    "read_file",
    "write_file",
    "edit_file",
    "create_directory",
    "list_directory",
    "find_files",
    "search_files",
    "file_info",
    "offer_download",
    "ask_user_question",
    "write_plan",
    "read_plan",
    "add_task",
    "update_task_status",
    "update_task_statuses",
    "remove_task",
    "remember",
    "update_memory",
    "forget",
    "save_skill",
]


def _unique[T](tools: list[T]) -> list[T]:
    if len(set(tools)) != len(tools):
        raise ValueError("an item is listed twice")
    return tools


type DisabledTools = Annotated[list[ToolName], AfterValidator(_unique)]
# The remote MCP servers that are off, by ID; an ID of no server is ignored (AGT-029, ADR-0099).
type DisabledServers = Annotated[list[uuid.UUID], Field(max_length=200), AfterValidator(_unique)]
# A skill's name by the Agent Skills rules, in ASCII; the API checks Unicode names by those rules (ADR-0096).
type SkillName = Annotated[str, Field(min_length=1, max_length=64)]
type DisabledSkills = Annotated[list[SkillName], Field(max_length=200), AfterValidator(_unique)]

# Tool permissions, approvals and audit events (AGT-002, AGT-005, AGT-008, ADR-0090).
type CapabilityClass = Literal[
    "reads_private_data", "ingests_untrusted", "external_communication", "irreversible", "physical"
]
type PermissionSetting = Literal["allow", "ask", "deny"]
type ApprovalScope = Literal["once", "turn", "conversation"]
type ApprovalOutcome = Literal["not_needed", "allowed", "approved", "denied", "expired", "refused"]
type ApprovalReason = Literal["untrusted_content", "tool_default", "permission", "consequential", "device"]


class ToolPermissions(Request):
    tools: dict[ToolName, PermissionSetting]
    classes: dict[CapabilityClass, PermissionSetting]
    # Remote MCP servers denied to the user (AGT-029, ADR-0099).
    servers: dict[uuid.UUID, Literal["deny"]] = Field(default_factory=dict[uuid.UUID, Literal["deny"]])


class ToolPermissionsOut(Response):
    tools: dict[str, PermissionSetting]
    classes: dict[str, PermissionSetting]
    # Left out when no server is denied (AGT-029).
    servers: dict[str, Literal["deny"]] = Field(default_factory=dict[str, Literal["deny"]])


class PermissionSource(Response):
    setting: PermissionSetting
    subject: str


class ToolInfo(Response):
    name: ToolName
    classes: list[CapabilityClass]
    approval_default: Literal["allow", "ask"]
    effective: PermissionSetting
    permission: PermissionSource | None


class ToolList(Response):
    items: list[ToolInfo]


class Allowances(Response):
    web_and_commands: bool
    tools: list[ToolName]


class AllowancesUpdate(Request):
    web_and_commands: bool
    tools: DisabledTools


class AuditEvent(Response):
    id: uuid.UUID
    tool: str
    conversation_id: uuid.UUID
    conversation_title: str | None
    run_id: uuid.UUID
    tool_call_id: str
    outcome: ApprovalOutcome
    scope: ApprovalScope | None
    reason: ApprovalReason | None
    repeated: bool
    created_at: Timestamp


class ActivityPage(Response):
    items: list[AuditEvent]
    next_cursor: str | None


class RunApproval(Response):
    tool_call_id: str
    outcome: ApprovalOutcome
    scope: ApprovalScope | None
    reason: ApprovalReason | None


# Postgres text holds no NUL character.
type Instructions = Annotated[str, Field(max_length=20000, pattern=r"^[^\x00]*$")]


class UserSettings(Request):
    """A user's defaults for their conversations (CNV-013, CNV-014)."""

    model: ModelChoice | None
    reasoning: Reasoning | None
    disabled_tools: DisabledTools
    # Optional: leaving it out keeps none off (AGT-029).
    disabled_servers: DisabledServers = Field(default_factory=list[uuid.UUID])
    base_instructions: Instructions | None
    additional_instructions: Instructions | None


class UserSettingsOut(Response):
    model: ModelChoiceOut | None
    reasoning: Reasoning | None
    disabled_tools: list[ToolName]
    disabled_servers: list[uuid.UUID]
    base_instructions: str | None
    additional_instructions: str | None
    built_in_base_instructions: str


class CreateConversationRequest(Request):
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    model: ModelChoice | None = None
    reasoning: Reasoning | None = None
    disabled_tools: DisabledTools | None = None
    disabled_servers: DisabledServers | None = None
    temporary: bool = False


class UpdateConversationRequest(Request):
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    archived: bool | None = None
    model: ModelChoice | None = None
    # Present and null moves the conversation out of its folder (CNV-007).
    folder_id: uuid.UUID | None = None
    pinned: bool | None = None
    reasoning: Reasoning | None = None
    disabled_tools: DisabledTools | None = None
    disabled_skills: DisabledSkills | None = None
    disabled_servers: DisabledServers | None = None
    # Only withdraws what the user allowed (AGT-006, ADR-0090).
    allowances: AllowancesUpdate | None = None
    # Present and null uses the user's defaults again (CNV-014).
    base_instructions: Instructions | None = None
    additional_instructions: Instructions | None = None


class ForkRequest(Request):
    run_id: uuid.UUID


class Money(Response):
    amount: str
    currency: str


class ForkedFrom(Response):
    conversation_id: uuid.UUID | None
    run_id: uuid.UUID | None


class Usage(Response):
    last_24_hours: list[Money]
    last_30_days: list[Money]
    unpriced_requests: int


class CreateFolderRequest(Request):
    name: Annotated[str, Field(min_length=1, max_length=100)]


class UpdateFolderRequest(Request):
    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    pinned: bool | None = None
    collapsed: bool | None = None


class Folder(Response):
    id: uuid.UUID
    name: str
    pinned: bool
    collapsed: bool
    last_message_at: Timestamp | None
    created_at: Timestamp


class SearchResult(Response):
    conversation_id: uuid.UUID
    title: str
    snippet: str
    last_message_at: Timestamp


class SearchResults(Response):
    items: list[SearchResult]


class RewindRequest(Request):
    run_id: uuid.UUID | None


class PlanStep(Response):
    id: str
    content: str
    active_form: str | None
    status: Literal["pending", "in_progress", "completed", "cancelled", "blocked"]


class Conversation(Response):
    id: uuid.UUID
    title: str
    archived: bool
    temporary: bool
    active_run_id: uuid.UUID | None
    model: ModelChoiceOut | None
    reasoning: Reasoning
    disabled_tools: list[ToolName]
    disabled_skills: list[str]
    disabled_servers: list[uuid.UUID]
    allowances: Allowances
    base_instructions: str | None
    additional_instructions: str | None
    folder_id: uuid.UUID | None
    pinned: bool
    forked_from: ForkedFrom | None
    # Pending questions as AG-UI interrupts, and the task list (AGT-015, UX-009, ADR-0083).
    interrupts: list[dict[str, Any]]
    plan: list[PlanStep]
    cost: list[Money]
    last_message_at: Timestamp
    created_at: Timestamp
    updated_at: Timestamp


class ConversationPage(Response):
    items: list[Conversation]
    next_cursor: str | None


class FolderEntry(Response):
    kind: Literal["folder"] = "folder"
    folder: Folder
    conversations: list[Conversation]


class ConversationEntry(Response):
    kind: Literal["conversation"] = "conversation"
    conversation: Conversation


class ConversationListPage(Response):
    items: list[FolderEntry | ConversationEntry]
    next_cursor: str | None


type RunKind = Literal["message", "resume"]


class RunError(Response):
    code: str
    reason: str | None


class PathRun(Response):
    run_id: uuid.UUID
    parent_run_id: uuid.UUID | None
    kind: RunKind
    message_ids: list[str]
    cost: list[Money]
    # Why the run failed, shown in place of its answer (UX-014).
    error: RunError | None
    # How the calls of the run that needed approval were decided (UX-023).
    approvals: list[RunApproval]


class MessagePage(Response):
    items: list[dict[str, Any]]
    runs: list[PathRun]
    next_cursor: str | None


class ModelRef(Response):
    connection_id: uuid.UUID | None
    provider: str
    model: str


class Run(Response):
    id: uuid.UUID
    conversation_id: uuid.UUID
    parent_run_id: uuid.UUID | None
    kind: RunKind
    status: Literal["queued", "running", "interrupted", "completed", "failed", "cancelled"]
    error_code: str | None
    model: ModelRef | None
    last_event_seq: int
    created_at: Timestamp
    started_at: Timestamp | None
    finished_at: Timestamp | None


class AgUiInputMessage(BaseModel):
    """A message of an AG-UI run input; only the last one, from the user, is used (ADR-0031)."""

    model_config = ConfigDict(extra="allow")

    id: str
    role: str
    content: Any = None


class RunInput(BaseModel):
    """The fields of an AG-UI `RunAgentInput` that the server uses; the others are ignored."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    thread_id: uuid.UUID = Field(alias="threadId")
    run_id: uuid.UUID = Field(alias="runId")
    parent_run_id: uuid.UUID | None = Field(default=None, alias="parentRunId")
    # Empty when `resume` answers an interrupt (ADR-0083).
    messages: list[AgUiInputMessage]
    resume: list[dict[str, Any]] | None = None
    # A Sibillo extension: how the message came, when it was not typed (UX-005, ADR-0088).
    voice: Literal["dictated", "hands_free"] | None = None
    # A Sibillo extension: the files attached to the message, already uploaded (CNV-017).
    attachments: Annotated[list[Annotated[str, Field(max_length=4096)]], Field(max_length=20)] = []


# A conversation's workspace (UX-019, ADR-0079).


class WorkspaceSummary(Response):
    size: int
    quota: int


class WorkspaceEntry(Response):
    name: str
    path: str
    type: Literal["file", "folder", "link"]
    size: int
    modified: Timestamp


class WorkspaceFolder(Response):
    path: str
    entries: list[WorkspaceEntry]


class WorkspacePathRequest(Request):
    path: Annotated[str, Field(min_length=1, max_length=4096)]


class WorkspaceMoveRequest(Request):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: Annotated[str, Field(alias="from", min_length=1, max_length=4096)]
    to: Annotated[str, Field(min_length=1, max_length=4096)]


# Memory (MEM-001 to MEM-008, ADR-0095).
def _memory_text(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 500:
        raise ValueError("a memory item holds 1 to 500 characters")
    return value


class MemorySetting(Request):
    enabled: bool


class MemoryItemText(Request):
    # Surrounding whitespace is removed before the limits are checked.
    text: Annotated[str, Field(max_length=500), AfterValidator(_memory_text)]


class MemoryConversation(Response):
    id: uuid.UUID
    title: str | None
    deleted: bool


class MemoryItem(Response):
    id: uuid.UUID
    text: str
    origin: Literal["user", "assistant"]
    untrusted: bool
    conversation: MemoryConversation | None
    created_at: Timestamp
    updated_at: Timestamp


class Memory(Response):
    enabled: bool
    items: list[MemoryItem]
    used_characters: int
    limit_characters: int


# Skills (AGT-017, AGT-024 to AGT-026, ADR-0096).


class SkillConversation(Response):
    id: uuid.UUID
    title: str | None
    deleted: bool


class Skill(Response):
    id: uuid.UUID | None
    name: str
    description: str
    builtin: bool
    enabled: bool
    origin: Literal["builtin", "user", "upload", "import", "assistant"]
    source_url: str | None
    conversation: SkillConversation | None
    untrusted: bool
    size_bytes: int
    created_at: Timestamp | None
    updated_at: Timestamp | None


class SkillFile(Response):
    path: str
    size_bytes: int
    executable: bool
    text: str | None


class SkillDetail(Skill):
    files: list[SkillFile]


class Skills(Response):
    builtin: list[Skill]
    own: list[Skill]
    used_bytes: int
    limit_bytes: int
    limit_skills: int


class SkillDocument(Request):
    skill_md: Annotated[str, Field(min_length=1, max_length=100_000)]


class SkillFileText(Request):
    text: Annotated[str, Field(max_length=1_048_576)]
    executable: bool = False


class UpdateSkillRequest(Request):
    enabled: bool | None = None
    untrusted: Literal[False] | None = None


class BuiltinSkillSetting(Request):
    enabled: bool


class SkillImportRequest(Request):
    url: Annotated[str, Field(min_length=3, max_length=2000)]
    names: Annotated[list[SkillName], Field(min_length=1), AfterValidator(_unique)] | None = None


class FoundSkill(Response):
    name: str
    description: str
    valid: bool
    # Left out when the skill is valid (ADR-0096).
    problem: Annotated[str | None, Field(exclude_if=lambda value: value is None)] = None


class SkillImport(Response):
    imported: list[Skill]
    found: list[FoundSkill]


# --- Remote MCP servers (AGT-019, AGT-028 to AGT-031, ADR-0099, ADR-0100) ---

type McpServerPrefix = Annotated[str, Field(min_length=1, max_length=20, pattern=r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")]
type McpServerAuth = Literal["none", "token", "oauth"]
type McpCredentialState = Literal["not_needed", "missing", "valid", "expired"]
type McpToolStatus = Literal["accepted", "changed", "gone", "not_accepted", "unusable"]
type McpToolProblem = Literal["name", "description_too_long", "schema_too_large", "too_many_tools", "requires_tasks"]
type McpServerName = Annotated[str, Field(min_length=1, max_length=100)]
type OAuthClientId = Annotated[str, Field(min_length=1, max_length=2000)]
type OAuthClientSecret = Annotated[str, Field(min_length=1, max_length=4000)]


class McpServerInfo(Response):
    name: str
    version: str


class McpOAuth(Response):
    issuer: str
    client_id: str
    client_registration: Literal["given", "metadata_document", "dynamic"]
    has_client_secret: bool
    scope: str | None


class McpToolDefinition(Response):
    title: str | None
    description: str | None
    input_schema: dict[str, Any]
    annotations: dict[str, Any] | None


class McpServerTool(Response):
    name: str
    model_name: str
    status: McpToolStatus
    listed: McpToolDefinition | None
    accepted: McpToolDefinition | None
    digest: str | None
    problem: McpToolProblem | None
    accepted_at: Timestamp | None


class McpServer(Response):
    id: uuid.UUID
    name: str
    prefix: str
    url: str
    auth: McpServerAuth
    oauth: McpOAuth | None
    credential: McpCredentialState
    private_network: bool
    enabled: bool
    server: McpServerInfo | None
    tools: list[McpServerTool]
    listed_at: Timestamp | None
    created_at: Timestamp
    updated_at: Timestamp


class McpServerList(Response):
    items: list[McpServer]


class CreateMcpServerRequest(Request):
    name: McpServerName
    prefix: McpServerPrefix
    url: Address
    auth: McpServerAuth
    oauth_client_id: OAuthClientId | None = None
    oauth_client_secret: OAuthClientSecret | None = None


class UpdateMcpServerRequest(Request):
    name: McpServerName | None = None
    url: Address | None = None
    auth: McpServerAuth | None = None
    # Present and null: Sibillo registers a client itself, or the client has no secret (ADR-0100).
    oauth_client_id: OAuthClientId | None = None
    oauth_client_secret: OAuthClientSecret | None = None
    enabled: bool | None = None


class AcceptedMcpTool(Request):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AcceptedMcpToolsRequest(Request):
    tools: Annotated[list[AcceptedMcpTool], Field(max_length=100)]


class McpSummaryTool(Response):
    model_name: str
    title: str | None
    description: str | None


class McpServerSummary(Response):
    id: uuid.UUID
    name: str
    prefix: str
    host: str
    auth: McpServerAuth
    credential: McpCredentialState
    denied: bool
    tools: list[McpSummaryTool]


class McpServerSummaryList(Response):
    items: list[McpServerSummary]


class McpCredentialRequest(Request):
    token: Annotated[str, Field(min_length=1, max_length=4000)]


class McpClientMetadata(Response):
    client_id: str
    client_name: str
    client_uri: str
    redirect_uris: list[str]
    grant_types: list[Literal["authorization_code", "refresh_token"]]
    response_types: list[Literal["code"]]
    token_endpoint_auth_method: Literal["none"]


class McpSignInStarted(Response):
    authorization_url: str
    expires_at: Timestamp


class CompleteMcpSignInRequest(Request):
    state: Annotated[str, Field(min_length=1, max_length=200)]
    code: Annotated[str, Field(min_length=1, max_length=4000)] | None = None
    iss: Annotated[str, Field(max_length=2000)] | None = None
    error: Annotated[str, Field(max_length=200)] | None = None
    error_description: Annotated[str, Field(max_length=2000)] | None = None
