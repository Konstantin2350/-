from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl

AgentName = Literal["crm", "calls", "chat", "knowledge", "tasks", "content", "finance"]


class Citation(BaseModel):
    document_id: UUID
    title: str
    version: int
    chunk: int
    excerpt: str
    score: float


class AgentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=30_000)
    session_id: str = Field(default_factory=lambda: str(uuid4()), max_length=128)
    user_id: str = Field(default="anonymous", max_length=128)
    tenant_id: str = Field(default="default", max_length=128)
    agent: AgentName | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    agent: AgentName
    answer: str
    data: dict[str, Any] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    requires_human: bool = False


class EmployeeProfile(BaseModel):
    id: str
    name: str
    role: str
    description: str
    primary_agent: AgentName | None = None
    skills: list[str]


class EmployeeInvokeRequest(BaseModel):
    message: str = Field(min_length=1, max_length=30_000)
    session_id: str = Field(default_factory=lambda: str(uuid4()), max_length=128)
    context: dict[str, Any] = Field(default_factory=dict)


class EmployeeResponse(BaseModel):
    employee: EmployeeProfile
    result: AgentResponse


class CRMExtractRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    current_fields: dict[str, Any] = Field(default_factory=dict)


class CRMEntity(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    amount: float | None = None
    product: str | None = None


class CRMExtractResponse(BaseModel):
    entities: CRMEntity
    field_updates: dict[str, Any]
    suggestions: dict[str, Any]
    relevance: Literal["relevant", "uncertain", "irrelevant"]
    confidence: float


class DealHistoryItem(BaseModel):
    customer_id: str
    won: bool
    amount: float = 0
    days_since_last_purchase: int = 0
    purchases: int = 0


class DealTrainingExample(BaseModel):
    text: str = ""
    amount: float = 0
    days_open: int = Field(default=0, ge=0)
    activities: int = Field(default=0, ge=0)
    won: bool


class DealModelTrainRequest(BaseModel):
    examples: list[DealTrainingExample] = Field(min_length=10, max_length=100_000)


class DealPredictRequest(BaseModel):
    text: str = ""
    amount: float = 0
    days_open: int = Field(default=0, ge=0)
    activities: int = Field(default=0, ge=0)


class CallAnalyzeRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=200_000)
    sales_script: list[str] = Field(default_factory=list)
    manager_name: str | None = None


class CallAnalysis(BaseModel):
    summary: str
    sentiment: Literal["positive", "neutral", "negative"]
    emotion_signals: list[str]
    script_score: float
    matched_steps: list[str]
    missing_steps: list[str]
    action_items: list[str]
    feedback: list[str]
    relevance: Literal["relevant", "irrelevant"]
    crm: CRMExtractResponse


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=30_000)
    user_id: str = Field(default="anonymous", max_length=128)
    tenant_id: str = Field(default="default", max_length=128)
    persona: Literal["sales", "support", "onboarding", "auto"] = "auto"
    channel: Literal["web", "bitrix24", "telegram", "whatsapp", "email", "api"] = "api"


class ChatResponse(BaseModel):
    answer: str
    persona: str
    history: list[dict[str, str]]
    citations: list[Citation] = Field(default_factory=list)
    handoff: bool = False
    handoff_reason: str | None = None
    handoff_id: UUID | None = None


class KnowledgeDocumentResponse(BaseModel):
    id: UUID
    title: str
    version: int
    chunks: int
    created_at: datetime


class KnowledgeQuery(BaseModel):
    question: str = Field(min_length=1, max_length=10_000)
    limit: int = Field(default=5, ge=1, le=20)


class KnowledgeAnswer(BaseModel):
    answer: str
    citations: list[Citation]


class TaskCreateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    available_assignees: list[dict[str, Any]] = Field(default_factory=list)


class TaskDraft(BaseModel):
    title: str
    description: str
    deadline: str | None = None
    priority: Literal["low", "normal", "high"]
    checklist: list[str]
    recommended_assignee: str | None = None
    risk_flags: list[str]


class BitrixCallRequest(BaseModel):
    method: str = Field(pattern=r"^[a-zA-Z0-9_.]+$")
    params: dict[str, Any] = Field(default_factory=dict)


class WebhookEnvelope(BaseModel):
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
    event_id: str | None = None


class ProcessDefinition(BaseModel):
    name: str
    trigger: str
    steps: list[dict[str, Any]]


class ActionCreateRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = True
    idempotency_key: str | None = Field(default=None, max_length=255)


class ActionConfirmRequest(BaseModel):
    payload_updates: dict[str, Any] = Field(default_factory=dict)


class ProcessStartRequest(BaseModel):
    process_id: UUID
    context: dict[str, Any] = Field(default_factory=dict)


class ProcessApprovalRequest(BaseModel):
    approved: bool = True
    comment: str | None = Field(default=None, max_length=2_000)


class HandoffClaimRequest(BaseModel):
    operator_id: str | None = Field(default=None, max_length=128)


class HandoffReplyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=30_000)
    close: bool = False


class ProcessNLRequest(BaseModel):
    description: str = Field(min_length=5, max_length=30_000)


class ContentRequest(BaseModel):
    kind: Literal["email", "product", "meta", "brainstorm", "meeting_summary", "article"]
    brief: str = Field(min_length=3, max_length=50_000)
    audience: str = Field(default="клиенты", max_length=500)
    tone: str = Field(default="деловой", max_length=100)


class PresentationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=10, max_length=100_000)
    slides: int = Field(default=6, ge=3, le=20)


class TrainingGenerateRequest(BaseModel):
    source: str = Field(min_length=20, max_length=100_000)
    count: int = Field(default=5, ge=1, le=50)


class TrainingEvaluateRequest(BaseModel):
    expected: str = Field(min_length=1, max_length=10_000)
    answer: str = Field(min_length=1, max_length=10_000)
    previous_scores: list[float] = Field(default_factory=list, max_length=100)


class ProcessEvent(BaseModel):
    case_id: str = Field(min_length=1, max_length=128)
    activity: str = Field(min_length=1, max_length=300)
    occurred_at: datetime


class ProcessMiningRequest(BaseModel):
    events: list[ProcessEvent] = Field(min_length=2, max_length=100_000)


class KPIForecastRequest(BaseModel):
    values: list[float] = Field(min_length=3, max_length=10_000)
    horizon: int = Field(default=3, ge=1, le=365)


class ProjectTask(BaseModel):
    title: str
    status: Literal["new", "in_progress", "done", "blocked"]
    due_date: date | None = None
    progress: int = Field(default=0, ge=0, le=100)
    assignee: str | None = None


class ProjectDigestRequest(BaseModel):
    project: str
    tasks: list[ProjectTask]


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=20_000)


class PersistTaskRequest(BaseModel):
    project_id: UUID | None = None
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=30_000)
    deadline: date | None = None
    priority: Literal["low", "normal", "high"] = "normal"
    assignee: str | None = Field(default=None, max_length=128)
    checklist: list[str] = Field(default_factory=list, max_length=100)
    risk_flags: list[str] = Field(default_factory=list, max_length=100)


class TaskUpdateRequest(BaseModel):
    status: Literal["new", "in_progress", "done", "blocked"] | None = None
    assignee: str | None = Field(default=None, max_length=128)
    deadline: date | None = None
    progress: int | None = Field(default=None, ge=0, le=100)


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)
    voice: str = Field(default="alloy", max_length=100)
    format: Literal["mp3", "wav", "opus", "aac", "flac"] = "mp3"


class MCPRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class URLCaptureRequest(BaseModel):
    url: HttpUrl
    prompt: str | None = None
