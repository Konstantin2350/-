from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl


AgentName = Literal["crm", "calls", "chat", "knowledge", "tasks", "content"]


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
    persona: Literal["sales", "support", "onboarding", "auto"] = "auto"


class ChatResponse(BaseModel):
    answer: str
    persona: str
    history: list[dict[str, str]]
    citations: list[Citation] = Field(default_factory=list)
    handoff: bool = False
    handoff_reason: str | None = None


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


class MCPRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class URLCaptureRequest(BaseModel):
    url: HttpUrl
    prompt: str | None = None
