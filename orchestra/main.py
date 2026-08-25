import asyncio
import json
import re
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Any
from urllib.parse import quote_plus
from uuid import uuid4

from fastapi import (
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import text

from orchestra import __version__
from orchestra.agents import build_orchestrator
from orchestra.campaigns import CampaignRegistry, LeadQualifier
from orchestra.capabilities import (
    AnalyticsService,
    AudioService,
    ContentService,
    ExternalProviderRequired,
    ProcessService,
    TrainingService,
)
from orchestra.config import Settings, get_settings
from orchestra.employees import EmployeeRegistry
from orchestra.infrastructure import ConversationMemory, Database
from orchestra.integrations import MCP_TOOLS, Bitrix24Client, WazzupClient
from orchestra.observability import AGENT_RUNS, metrics_middleware, metrics_response
from orchestra.schemas import (
    ActionConfirmRequest,
    ActionCreateRequest,
    AgentRequest,
    BitrixCallRequest,
    CallAnalyzeRequest,
    ChatRequest,
    ContentRequest,
    CRMExtractRequest,
    DealHistoryItem,
    DealModelTrainRequest,
    DealPredictRequest,
    EmployeeInvokeRequest,
    HandoffClaimRequest,
    HandoffReplyRequest,
    KnowledgeQuery,
    KPIForecastRequest,
    LeadIntakeRequest,
    LeadUpdateRequest,
    MCPRequest,
    PersistTaskRequest,
    PresentationRequest,
    ProcessApprovalRequest,
    ProcessDefinition,
    ProcessMiningRequest,
    ProcessNLRequest,
    ProcessStartRequest,
    ProjectCreateRequest,
    ProjectDigestRequest,
    SpeechRequest,
    TaskCreateRequest,
    TaskUpdateRequest,
    TrainingEvaluateRequest,
    TrainingGenerateRequest,
    WazzupWebhook,
    WebhookEnvelope,
)
from orchestra.security import ROLE_LEVELS, Authenticator, RateLimiter
from orchestra.worker import celery_app
from orchestra.workflows import ActionEngine, ProcessEngine, WorkflowConflict


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = Database(settings)
    memory = ConversationMemory(settings)
    orchestrator, knowledge, crm, calls, tasks = build_orchestrator(settings, db, memory)
    bitrix = Bitrix24Client(settings)
    wazzup = WazzupClient(settings)
    action_engine = ActionEngine(db, bitrix)
    process_engine = ProcessEngine(db, orchestrator, settings)
    authenticator = Authenticator(settings)
    rate_limiter = RateLimiter(settings)
    audio = AudioService(settings)
    processes = ProcessService()
    content = ContentService(orchestrator.llm)
    training = TrainingService(knowledge.embeddings)
    analytics = AnalyticsService()
    employees = EmployeeRegistry(settings, orchestrator)
    campaigns = CampaignRegistry(settings)
    lead_qualifier = LeadQualifier()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.production_issues:
            raise RuntimeError(
                "Unsafe production configuration: " + "; ".join(settings.production_issues)
            )
        if settings.environment != "production":
            await db.create_schema()
        yield
        await rate_limiter.close()
        await memory.close()
        await db.close()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Multi-agent business automation platform with Bitrix24 and MCP",
        lifespan=lifespan,
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None if settings.environment == "production" else "/redoc",
        openapi_url=None if settings.environment == "production" else "/openapi.json",
    )
    app.state.settings = settings
    app.state.db = db
    app.state.orchestrator = orchestrator
    app.state.bitrix = bitrix
    app.state.wazzup = wazzup
    app.state.employees = employees
    app.state.campaigns = campaigns

    def action_payload(action) -> dict[str, Any]:
        return {
            "id": action.id,
            "tool": action.tool,
            "status": action.status,
            "payload": action.payload,
            "requires_confirmation": action.requires_confirmation,
            "result": action.result,
            "error": action.error,
            "created_at": action.created_at,
            "updated_at": action.updated_at,
        }

    def process_instance_payload(instance) -> dict[str, Any]:
        return {
            "id": instance.id,
            "process_id": instance.process_id,
            "status": instance.status,
            "current_step": instance.current_step,
            "context": instance.context,
            "history": instance.history,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        }

    def handoff_payload(handoff) -> dict[str, Any]:
        return {
            "id": handoff.id,
            "session_id": handoff.session_id,
            "user_id": handoff.user_id,
            "channel": handoff.channel,
            "status": handoff.status,
            "reason": handoff.reason,
            "assigned_to": handoff.assigned_to,
            "history": handoff.history,
            "replies": handoff.replies,
            "created_at": handoff.created_at,
            "updated_at": handoff.updated_at,
        }

    def lead_payload(lead) -> dict[str, Any]:
        return {
            "id": lead.id,
            "campaign_code": lead.campaign_code,
            "external_id": lead.external_id,
            "session_id": lead.session_id,
            "channel": lead.channel,
            "name": lead.name,
            "phone": lead.phone,
            "answers": lead.answers,
            "history": lead.history,
            "status": lead.status,
            "priority": lead.priority,
            "qualification_score": lead.qualification_score,
            "next_question": lead.next_question,
            "handoff_id": lead.handoff_id,
            "created_at": lead.created_at,
            "updated_at": lead.updated_at,
        }

    def campaign_payload(campaign) -> dict[str, Any]:
        contact_links = {}
        for channel in campaign.channels:
            try:
                campaigns.destination_url(campaign, channel)
            except ValueError:
                continue
            contact_links[channel] = campaigns.public_link(campaign, channel)
        return {
            **campaign.model_dump(mode="json"),
            "public_link": campaigns.public_link(campaign),
            "contact_links": contact_links,
            "configured_channels": list(contact_links),
        }

    def task_payload(task) -> dict[str, Any]:
        return {
            "id": task.id,
            "project_id": task.project_id,
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "priority": task.priority,
            "deadline": task.deadline,
            "assignee": task.assignee,
            "progress": task.progress,
            "checklist": task.checklist,
            "risk_flags": task.risk_flags,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.middleware("http")(metrics_middleware)

    @app.middleware("http")
    async def security_and_trace(request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid4()))
        public_paths = {"/health", "/ready", "/docs", "/openapi.json", "/redoc"}
        is_webhook = request.url.path.startswith("/v1/webhooks/")
        is_public_redirect = request.url.path.startswith("/r/")
        principal = authenticator.from_request(request)
        if (
            request.url.path not in public_paths
            and not is_webhook
            and not is_public_redirect
            and not principal
        ):
            return JSONResponse(
                {"detail": "Authentication required", "request_id": request_id},
                status_code=401,
            )
        if principal:
            minimum_role = "viewer"
            if request.method != "GET":
                minimum_role = "operator"
            if request.url.path.startswith(
                (
                    "/v1/bitrix",
                    "/v1/processes",
                    "/v1/jobs",
                    "/v1/integrations",
                    "/v1/analytics",
                    "/v1/crm/deal-model",
                    "/v1/actions",
                    "/v1/operator",
                )
            ):
                minimum_role = "manager"
            if request.url.path.startswith("/v1/admin"):
                minimum_role = "admin"
            if ROLE_LEVELS[principal.role] < ROLE_LEVELS[minimum_role]:
                return JSONResponse(
                    {"detail": f"Role {minimum_role} required", "request_id": request_id},
                    status_code=403,
                )
            try:
                allowed, remaining = await rate_limiter.allow(
                    f"{principal.tenant_id}:{principal.user_id}"
                )
            except Exception:
                return JSONResponse(
                    {
                        "detail": "Rate limiter unavailable",
                        "request_id": request_id,
                    },
                    status_code=503,
                )
            if not allowed:
                return JSONResponse(
                    {"detail": "Rate limit exceeded", "request_id": request_id},
                    status_code=429,
                    headers={"retry-after": "60"},
                )
            request.state.principal = principal
        else:
            remaining = settings.rate_limit_per_minute
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-ratelimit-remaining"] = str(remaining)
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "no-referrer"
        if settings.environment == "production":
            response.headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": __version__,
            "llm": "configured" if settings.llm_api_key else "local-fallback",
        }

    @app.get("/ready", tags=["system"])
    async def ready() -> dict[str, Any]:
        if settings.production_issues:
            raise HTTPException(
                status_code=503,
                detail={"configuration": settings.production_issues},
            )
        try:
            async with db.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as error:
            raise HTTPException(status_code=503, detail="Database unavailable") from error
        try:
            redis_ready = await memory.ping()
        except Exception as error:
            raise HTTPException(status_code=503, detail="Redis unavailable") from error
        celery_ready: bool | None = None
        if settings.environment == "production":
            replies = await asyncio.to_thread(lambda: celery_app.control.ping(timeout=1.5))
            celery_ready = bool(replies)
            if not celery_ready:
                raise HTTPException(status_code=503, detail="Celery worker unavailable")
        return {
            "status": "ready",
            "components": {
                "database": "ready",
                "redis": (
                    "not-configured"
                    if memory.redis is None
                    else "ready"
                    if redis_ready
                    else "unavailable"
                ),
                "celery": ("ready" if celery_ready else "not-checked"),
            },
        }

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return metrics_response()

    async def redirect_to_campaign_channel(campaign_code: str, channel: str | None = None):
        campaign = campaigns.get(campaign_code)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        try:
            destination = campaigns.destination_url(campaign, channel)
        except ValueError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        resolved_channel = channel or campaign.channel
        await db.append_event(
            "campaign.link_clicked",
            "public",
            {
                "campaign_code": campaign.code,
                "source": campaign.source,
                "channel": resolved_channel,
            },
            tenant_id=campaign.tenant_id,
        )
        return RedirectResponse(destination, status_code=307)

    @app.get("/r/{campaign_code}/{channel}", tags=["campaigns"], include_in_schema=False)
    async def campaign_channel_redirect(campaign_code: str, channel: str):
        return await redirect_to_campaign_channel(campaign_code, channel)

    @app.get("/r/{campaign_code}", tags=["campaigns"], include_in_schema=False)
    async def campaign_redirect(campaign_code: str):
        return await redirect_to_campaign_channel(campaign_code)

    @app.get("/v1/campaigns", tags=["campaigns"])
    async def list_campaigns(request: Request):
        return {
            "campaigns": [
                campaign_payload(campaign)
                for campaign in campaigns.list(request.state.principal.tenant_id)
            ]
        }

    @app.get("/v1/campaigns/{campaign_code}", tags=["campaigns"])
    async def get_campaign(campaign_code: str, request: Request):
        campaign = campaigns.get(campaign_code, request.state.principal.tenant_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        return campaign_payload(campaign)

    @app.post("/v1/webhooks/leads/{campaign_code}", tags=["campaigns"])
    async def ingest_campaign_lead(
        campaign_code: str,
        body: LeadIntakeRequest,
        x_webhook_secret: Annotated[str | None, Header()] = None,
        x_tenant_id: Annotated[str, Header()] = "default",
    ):
        expected_secret = settings.webhook_secret_map.get(x_tenant_id)
        if expected_secret and not secrets.compare_digest(x_webhook_secret or "", expected_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        if settings.webhook_secret_map and not expected_secret:
            raise HTTPException(status_code=401, detail="Unknown webhook tenant")
        campaign = campaigns.get(campaign_code, x_tenant_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        existing = await db.find_lead(x_tenant_id, campaign_code, body.external_id)
        extracted = crm.extract(body.message).entities
        name = (
            body.name
            or (existing.name if existing else None)
            or extracted.name
            or lead_qualifier.extract_name(body.message)
        )
        phone = lead_qualifier.normalize_phone(
            body.phone or (existing.phone if existing else None) or extracted.phone
        )
        answers = {**(existing.answers if existing else {}), **body.answers}
        qualification = lead_qualifier.evaluate(campaign, body.message, name, phone, answers)
        values = {
            "session_id": body.session_id or body.external_id,
            "channel": body.channel,
            **{
                key: value
                for key, value in qualification.items()
                if key != "reply" and key != "handoff_required"
            },
        }
        lead, created = await db.upsert_lead(
            x_tenant_id, campaign_code, body.external_id, values, body.message
        )
        history = list(lead.history)
        reply = str(qualification["reply"])
        if not history or history[-1] != {"role": "assistant", "content": reply}:
            history.append({"role": "assistant", "content": reply})
            lead = await db.update_lead(lead.id, x_tenant_id, {"history": history[-100:]})
            assert lead

        if qualification["handoff_required"] and not lead.handoff_id:
            handoff = await db.create_handoff(
                tenant_id=x_tenant_id,
                session_id=lead.session_id,
                user_id=lead.phone or lead.external_id,
                channel=lead.channel,
                reason=(
                    f"Лид кампании {campaign.name}; приоритет {lead.priority}; "
                    f"SLA {campaign.response_sla_minutes} мин."
                ),
                history=lead.history,
            )
            lead = await db.update_lead(lead.id, x_tenant_id, {"handoff_id": handoff.id})
            assert lead

        if created:
            await db.append_event(
                "campaign.lead_created",
                "lead-webhook",
                {
                    "campaign_code": campaign.code,
                    "lead_id": lead.id,
                    "priority": lead.priority,
                },
                external_id=f"lead:{x_tenant_id}:{campaign.code}:{body.external_id}",
                tenant_id=x_tenant_id,
            )
        return {
            "created": created,
            "reply": reply,
            "lead": lead_payload(lead),
        }

    @app.post("/v1/webhooks/wazzup/{campaign_code}", tags=["campaigns"])
    async def wazzup_webhook(
        campaign_code: str,
        body: WazzupWebhook,
        request: Request,
        x_tenant_id: Annotated[str, Header()] = "default",
    ):
        if settings.wazzup_webhook_token:
            authorization = request.headers.get("authorization", "")
            bearer = (
                authorization.removeprefix("Bearer ").strip()
                if authorization.startswith("Bearer ")
                else ""
            )
            supplied_token = request.query_params.get("token", "") or bearer
            if not secrets.compare_digest(supplied_token, settings.wazzup_webhook_token):
                raise HTTPException(status_code=401, detail="Invalid Wazzup webhook token")
        if body.test:
            return {"status": "ok"}
        campaign = campaigns.get(campaign_code, x_tenant_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        processed = []
        for message in body.messages:
            if (
                message.status != "inbound"
                or message.is_echo
                or message.message_type != "text"
                or not message.text
                or message.chat_type not in campaign.channels
            ):
                continue
            event_id = f"wazzup:{x_tenant_id}:{message.message_id}"
            if await db.event_exists(event_id, x_tenant_id):
                processed.append({"message_id": message.message_id, "status": "duplicate"})
                continue
            internal_secret = settings.webhook_secret_map.get(x_tenant_id)
            result = await ingest_campaign_lead(
                campaign_code,
                LeadIntakeRequest(
                    external_id=f"wazzup:{message.chat_type}:{message.chat_id}",
                    session_id=f"wazzup:{message.chat_id}",
                    channel=message.chat_type,
                    message=message.text,
                    name=message.contact.name,
                    phone=message.contact.phone,
                ),
                x_webhook_secret=internal_secret,
                x_tenant_id=x_tenant_id,
            )
            lead_info = result["lead"]
            if not lead_info["handoff_id"]:
                handoff = await db.create_handoff(
                    tenant_id=x_tenant_id,
                    session_id=lead_info["session_id"],
                    user_id=message.contact.username or message.chat_id,
                    channel=message.chat_type,
                    reason=(
                        f"Входящий лид Wazzup: {campaign.name}; "
                        f"SLA {campaign.response_sla_minutes} мин."
                    ),
                    history=lead_info["history"],
                )
                lead = await db.update_lead(
                    lead_info["id"], x_tenant_id, {"handoff_id": handoff.id}
                )
                assert lead
                result["lead"] = lead_payload(lead)

            delivery = "disabled"
            if settings.wazzup_auto_reply:
                try:
                    sent = await wazzup.send_message(
                        channel_id=message.channel_id,
                        chat_type=message.chat_type,
                        chat_id=message.chat_id,
                        text=result["reply"],
                        crm_message_id=f"orchestra:{message.message_id}",
                    )
                    delivery = "sent"
                    result["provider_message_id"] = sent.get("messageId")
                except Exception:
                    delivery = "failed"
            await db.append_event(
                "wazzup.message_processed",
                "wazzup-webhook",
                {
                    "campaign_code": campaign.code,
                    "lead_id": result["lead"]["id"],
                    "chat_type": message.chat_type,
                    "delivery": delivery,
                },
                external_id=event_id,
                tenant_id=x_tenant_id,
            )
            processed.append(
                {
                    "message_id": message.message_id,
                    "status": "processed",
                    "delivery": delivery,
                    "lead_id": result["lead"]["id"],
                    "handoff_id": result["lead"]["handoff_id"],
                }
            )
        return {"status": "ok", "processed": processed}

    @app.post(
        "/v1/integrations/wazzup/subscribe/{campaign_code}",
        tags=["integrations"],
    )
    async def subscribe_wazzup(campaign_code: str, request: Request):
        tenant_id = request.state.principal.tenant_id
        if not campaigns.get(campaign_code, tenant_id):
            raise HTTPException(status_code=404, detail="Campaign not found")
        if not settings.wazzup_api_key:
            raise HTTPException(status_code=409, detail="WAZZUP_API_KEY is not configured")
        if not settings.wazzup_webhook_token:
            raise HTTPException(status_code=409, detail="WAZZUP_WEBHOOK_TOKEN is not configured")
        callback = (
            f"{settings.public_base_url.rstrip('/')}/v1/webhooks/wazzup/{campaign_code}"
            f"?token={quote_plus(settings.wazzup_webhook_token)}"
        )
        try:
            provider_result = await wazzup.subscribe(callback)
        except Exception as error:
            raise HTTPException(status_code=502, detail="Wazzup setup failed") from error
        return {"status": "configured", "provider": provider_result}

    @app.get("/v1/leads", tags=["campaigns"])
    async def list_leads(
        request: Request,
        campaign_code: str | None = None,
        status: str | None = None,
    ):
        records = await db.list_leads(request.state.principal.tenant_id, campaign_code, status)
        return {"leads": [lead_payload(item) for item in records]}

    @app.patch("/v1/leads/{lead_id}", tags=["campaigns"])
    async def update_lead(lead_id: str, body: LeadUpdateRequest, request: Request):
        tenant_id = request.state.principal.tenant_id
        current = await db.get_lead(lead_id, tenant_id)
        if not current:
            raise HTTPException(status_code=404, detail="Lead not found")
        campaign = campaigns.get(current.campaign_code, tenant_id)
        if not campaign:
            raise HTTPException(status_code=409, detail="Campaign configuration is missing")
        answers = {**current.answers, **body.answers}
        name = body.name or current.name
        phone = lead_qualifier.normalize_phone(body.phone or current.phone)
        last_message = next(
            (item["content"] for item in reversed(current.history) if item.get("role") == "client"),
            "",
        )
        qualification = lead_qualifier.evaluate(campaign, last_message, name, phone, answers)
        values = {
            key: value
            for key, value in qualification.items()
            if key not in {"reply", "handoff_required"}
        }
        if body.status:
            values["status"] = body.status
        updated = await db.update_lead(lead_id, tenant_id, values)
        assert updated
        return lead_payload(updated)

    @app.get("/v1/campaigns/{campaign_code}/metrics", tags=["campaigns"])
    async def campaign_metrics(campaign_code: str, request: Request):
        tenant_id = request.state.principal.tenant_id
        if not campaigns.get(campaign_code, tenant_id):
            raise HTTPException(status_code=404, detail="Campaign not found")
        leads = await db.list_leads(tenant_id, campaign_code)
        events = await db.recent_events(10_000, tenant_id)
        status_counts: dict[str, int] = {}
        priority_counts: dict[str, int] = {}
        for lead in leads:
            status_counts[lead.status] = status_counts.get(lead.status, 0) + 1
            priority_counts[lead.priority] = priority_counts.get(lead.priority, 0) + 1
        click_events = [
            event
            for event in events
            if event.event_type == "campaign.link_clicked"
            and event.payload.get("campaign_code") == campaign_code
        ]
        clicks_by_channel: dict[str, int] = {}
        for event in click_events:
            channel = str(event.payload.get("channel", "unknown"))
            clicks_by_channel[channel] = clicks_by_channel.get(channel, 0) + 1
        return {
            "campaign_code": campaign_code,
            "clicks": len(click_events),
            "clicks_by_channel": clicks_by_channel,
            "leads": len(leads),
            "with_phone": sum(bool(lead.phone) for lead in leads),
            "handoffs": sum(bool(lead.handoff_id) for lead in leads),
            "statuses": status_counts,
            "priorities": priority_counts,
        }

    @app.post("/v1/orchestrate", tags=["agents"])
    async def orchestrate(body: AgentRequest, request: Request):
        principal = request.state.principal
        body = body.model_copy(
            update={
                "user_id": principal.user_id,
                "tenant_id": principal.tenant_id,
            }
        )
        response = await orchestrator.execute(body)
        AGENT_RUNS.labels(response.agent, str(response.requires_human).lower()).inc()
        return response

    @app.get("/v1/employees", tags=["employees"])
    async def list_employees():
        return {"employees": employees.list()}

    @app.get("/v1/employees/{employee_id}", tags=["employees"])
    async def get_employee(employee_id: str):
        employee = employees.get(employee_id)
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        return employee

    @app.post("/v1/employees/{employee_id}/invoke", tags=["employees"])
    async def invoke_employee(employee_id: str, body: EmployeeInvokeRequest, request: Request):
        principal = request.state.principal
        try:
            return await employees.invoke(
                employee_id,
                body,
                principal.user_id,
                principal.tenant_id,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Employee not found") from error

    @app.post("/v1/jobs/agent", tags=["agents"], status_code=202)
    async def enqueue_agent(body: AgentRequest, request: Request):
        principal = request.state.principal
        body = body.model_copy(
            update={
                "user_id": principal.user_id,
                "tenant_id": principal.tenant_id,
            }
        )
        try:
            job = celery_app.send_task("orchestra.run_agent", args=[body.model_dump(mode="json")])
        except Exception as error:
            raise HTTPException(status_code=503, detail="Task queue unavailable") from error
        return {"job_id": job.id, "status": "queued"}

    @app.get("/v1/jobs/{job_id}", tags=["agents"])
    async def job_status(job_id: str):
        result = celery_app.AsyncResult(job_id)
        response: dict[str, Any] = {"job_id": job_id, "status": result.status}
        if result.successful():
            response["result"] = result.result
        elif result.failed():
            response["error"] = str(result.result)
        return response

    @app.post("/v1/actions", tags=["actions"], status_code=201)
    async def create_action(body: ActionCreateRequest, request: Request):
        principal = request.state.principal
        action = await db.create_action(
            tenant_id=principal.tenant_id,
            actor=principal.user_id,
            tool=body.tool,
            payload=body.payload,
            requires_confirmation=body.requires_confirmation,
            idempotency_key=body.idempotency_key,
        )
        return action_payload(action)

    @app.get("/v1/actions", tags=["actions"])
    async def list_actions(request: Request, status: str | None = None):
        records = await db.list_actions(request.state.principal.tenant_id, status)
        return {"actions": [action_payload(item) for item in records]}

    @app.post("/v1/actions/{action_id}/confirm", tags=["actions"])
    async def confirm_action(action_id: str, body: ActionConfirmRequest, request: Request):
        try:
            action = await action_engine.confirm(
                action_id,
                request.state.principal.tenant_id,
                body.payload_updates,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Action not found") from error
        except WorkflowConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return action_payload(action)

    @app.post("/v1/actions/{action_id}/execute", tags=["actions"])
    async def execute_action(action_id: str, request: Request):
        try:
            action = await action_engine.execute(action_id, request.state.principal.tenant_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Action not found") from error
        except WorkflowConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return action_payload(action)

    @app.post("/v1/actions/{action_id}/enqueue", tags=["actions"], status_code=202)
    async def enqueue_action(action_id: str, request: Request):
        tenant_id = request.state.principal.tenant_id
        action = await db.get_action(action_id, tenant_id)
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")
        if action.status != "confirmed":
            raise HTTPException(status_code=409, detail="Confirm action first")
        try:
            job = celery_app.send_task("orchestra.execute_action", args=[action_id, tenant_id])
        except Exception as error:
            raise HTTPException(status_code=503, detail="Task queue unavailable") from error
        return {"job_id": job.id, "action_id": action_id, "status": "queued"}

    @app.post("/v1/crm/extract", tags=["crm"])
    async def crm_extract(body: CRMExtractRequest):
        return crm.extract(body.text, body.current_fields)

    @app.post("/v1/crm/repeat-sales", tags=["crm"])
    async def crm_repeat_sales(body: list[DealHistoryItem]):
        return {"customers": crm.repeat_sales(body)}

    @app.post("/v1/crm/deal-model/train", tags=["crm"])
    async def train_deal_model(body: DealModelTrainRequest, request: Request):
        try:
            parameters, model_metrics = crm.train_deal_model(body.examples)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        model = await db.save_model(
            "deal_outcome",
            parameters,
            model_metrics,
            request.state.principal.tenant_id,
        )
        return {
            "model_id": model.id,
            "version": model.version,
            "metrics": model.metrics,
        }

    @app.post("/v1/crm/deal-model/predict", tags=["crm"])
    async def predict_deal(body: DealPredictRequest, request: Request):
        model = await db.active_model("deal_outcome", request.state.principal.tenant_id)
        if not model:
            raise HTTPException(status_code=409, detail="Train a deal model first")
        try:
            probability = crm.predict_deal(body, model.parameters)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "probability": probability,
            "model_version": model.version,
            "model_metrics": model.metrics,
        }

    @app.post("/v1/calls/analyze", tags=["calls"])
    async def analyze_call(body: CallAnalyzeRequest):
        return calls.analyze(body.transcript, body.sales_script)

    @app.post("/v1/calls/transcribe", tags=["calls"])
    async def transcribe_call(
        file: Annotated[UploadFile, File()],
        language: Annotated[str | None, Form()] = None,
    ):
        raw = await file.read(settings.max_audio_bytes + 1)
        try:
            transcript = await audio.transcribe(file.filename or "call.mp3", raw, language)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ExternalProviderRequired as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {"transcript": transcript, "language": language or "auto"}

    @app.post("/v1/calls/process-audio", tags=["calls"])
    async def process_audio_call(
        file: Annotated[UploadFile, File()],
        sales_script: Annotated[str, Form()] = "[]",
        language: Annotated[str | None, Form()] = None,
    ):
        raw = await file.read(settings.max_audio_bytes + 1)
        try:
            script = json.loads(sales_script)
            if not isinstance(script, list) or not all(isinstance(item, str) for item in script):
                raise ValueError("sales_script must be a JSON array of strings")
            transcript = await audio.transcribe(file.filename or "call.mp3", raw, language)
        except (ValueError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ExternalProviderRequired as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {
            "transcript": transcript,
            "analysis": calls.analyze(transcript, script).model_dump(),
            "audio_signals": audio.wav_signals(raw, transcript),
        }

    @app.post("/v1/chat/messages", tags=["chat"])
    async def chat(body: ChatRequest, request: Request):
        principal = request.state.principal
        body = body.model_copy(
            update={
                "user_id": principal.user_id,
                "tenant_id": principal.tenant_id,
            }
        )
        return await orchestrator.chat(body)

    @app.post("/v1/channels/{channel}/messages", tags=["chat"])
    async def channel_message(channel: str, body: ChatRequest, request: Request):
        supported = {"web", "bitrix24", "telegram", "whatsapp", "email", "api"}
        if channel not in supported:
            raise HTTPException(status_code=422, detail="Unsupported channel")
        principal = request.state.principal
        return await orchestrator.chat(
            body.model_copy(
                update={
                    "channel": channel,
                    "user_id": principal.user_id,
                    "tenant_id": principal.tenant_id,
                }
            )
        )

    @app.websocket("/v1/chat/ws/{session_id}")
    async def chat_socket(websocket: WebSocket, session_id: str):
        supplied_key = websocket.query_params.get("api_key", "")
        authorization = websocket.headers.get("authorization", "")
        principal = authenticator.authenticate(authorization, supplied_key)
        if not principal or not principal.can("operator"):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                allowed, _ = await rate_limiter.allow(f"{principal.tenant_id}:{principal.user_id}")
                if not allowed:
                    await websocket.send_json({"error": "Rate limit exceeded"})
                    await websocket.close(code=1013)
                    return
                payload = await websocket.receive_json()
                response = await orchestrator.chat(
                    ChatRequest(
                        session_id=session_id,
                        message=payload.get("message", ""),
                        user_id=principal.user_id,
                        tenant_id=principal.tenant_id,
                        persona=payload.get("persona", "auto"),
                    )
                )
                await websocket.send_json(response.model_dump(mode="json"))
        except WebSocketDisconnect:
            return

    @app.get("/v1/operator/handoffs", tags=["operators"])
    async def list_operator_handoffs(request: Request, status: str | None = "queued"):
        records = await db.list_handoffs(request.state.principal.tenant_id, status)
        return {"handoffs": [handoff_payload(item) for item in records]}

    @app.post("/v1/operator/handoffs/{handoff_id}/claim", tags=["operators"])
    async def claim_handoff(handoff_id: str, body: HandoffClaimRequest, request: Request):
        principal = request.state.principal
        records = await db.list_handoffs(principal.tenant_id)
        current = next((item for item in records if item.id == handoff_id), None)
        if not current:
            raise HTTPException(status_code=404, detail="Handoff not found")
        if current.status not in {"queued", "claimed"}:
            raise HTTPException(status_code=409, detail="Handoff is closed")
        updated = await db.update_handoff(
            handoff_id,
            principal.tenant_id,
            status="claimed",
            assigned_to=body.operator_id or principal.user_id,
        )
        assert updated
        return handoff_payload(updated)

    @app.post("/v1/operator/handoffs/{handoff_id}/reply", tags=["operators"])
    async def reply_handoff(handoff_id: str, body: HandoffReplyRequest, request: Request):
        principal = request.state.principal
        records = await db.list_handoffs(principal.tenant_id)
        current = next((item for item in records if item.id == handoff_id), None)
        if not current:
            raise HTTPException(status_code=404, detail="Handoff not found")
        if current.status != "claimed":
            raise HTTPException(status_code=409, detail="Claim handoff first")
        replies = list(current.replies)
        replies.append(
            {
                "operator_id": principal.user_id,
                "message": body.message,
            }
        )
        updated = await db.update_handoff(
            handoff_id,
            principal.tenant_id,
            replies=replies,
            status="closed" if body.close else "claimed",
        )
        assert updated
        await db.append_event(
            "handoff.operator_reply",
            principal.user_id,
            {
                "handoff_id": handoff_id,
                "channel": current.channel,
                "closed": body.close,
            },
            tenant_id=principal.tenant_id,
        )
        return {
            **handoff_payload(updated),
            "delivery": "recorded",
        }

    @app.post("/v1/knowledge/documents", tags=["knowledge"])
    async def upload_document(
        request: Request,
        file: Annotated[UploadFile, File()],
        title: Annotated[str | None, Form()] = None,
    ):
        content = await file.read(settings.max_upload_bytes + 1)
        try:
            return await knowledge.ingest(
                file.filename or "document.txt",
                content,
                title,
                request.state.principal.tenant_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/knowledge/query", tags=["knowledge"])
    async def query_knowledge(body: KnowledgeQuery, request: Request):
        return await knowledge.answer(
            body.question,
            body.limit,
            request.state.principal.tenant_id,
        )

    @app.post("/v1/tasks/from-text", tags=["tasks"])
    async def task_from_text(body: TaskCreateRequest):
        return tasks.create(body.text, body.available_assignees)

    @app.post("/v1/projects", tags=["tasks"], status_code=201)
    async def create_project(body: ProjectCreateRequest, request: Request):
        project = await db.create_project(
            request.state.principal.tenant_id, body.name, body.description
        )
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "created_at": project.created_at,
        }

    @app.get("/v1/projects", tags=["tasks"])
    async def list_projects(request: Request):
        records = await db.list_projects(request.state.principal.tenant_id)
        return {
            "projects": [
                {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description,
                    "status": item.status,
                    "created_at": item.created_at,
                }
                for item in records
            ]
        }

    @app.post("/v1/tasks", tags=["tasks"], status_code=201)
    async def persist_task(body: PersistTaskRequest, request: Request):
        values = body.model_dump(mode="json")
        values["project_id"] = str(body.project_id) if body.project_id else None
        values["status"] = "new"
        values["progress"] = 0
        try:
            task = await db.create_task(request.state.principal.tenant_id, values)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return task_payload(task)

    @app.get("/v1/projects/{project_id}/tasks", tags=["tasks"])
    async def list_project_tasks(project_id: str, request: Request):
        records = await db.list_tasks(request.state.principal.tenant_id, project_id)
        return {"tasks": [task_payload(item) for item in records]}

    @app.patch("/v1/tasks/{task_id}", tags=["tasks"])
    async def update_task(task_id: str, body: TaskUpdateRequest, request: Request):
        values = body.model_dump(mode="json", exclude_unset=True)
        task = await db.update_task(task_id, request.state.principal.tenant_id, values)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task_payload(task)

    @app.post("/v1/tasks/{task_id}/sync-bitrix", tags=["tasks"])
    async def sync_task_to_bitrix(task_id: str, request: Request):
        principal = request.state.principal
        records = await db.list_tasks(principal.tenant_id)
        task = next((item for item in records if item.id == task_id), None)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        action = await db.create_action(
            tenant_id=principal.tenant_id,
            actor=principal.user_id,
            tool="bitrix.call",
            payload={
                "method": "tasks.task.add",
                "params": {
                    "fields": {
                        "TITLE": task.title,
                        "DESCRIPTION": task.description,
                        "DEADLINE": task.deadline,
                        "RESPONSIBLE_ID": task.assignee,
                    }
                },
            },
            requires_confirmation=True,
            idempotency_key=f"task:{task.id}:bitrix-sync",
        )
        return action_payload(action)

    @app.post("/v1/processes/compile", tags=["automation"])
    async def compile_process(body: ProcessDefinition):
        invalid = processes.validate(body.steps)
        if invalid:
            raise HTTPException(
                status_code=422, detail=f"Unsupported step types at indexes: {invalid}"
            )
        return {
            "dsl_version": "1.0",
            "process": body.model_dump(),
            "validation": {"valid": True, "steps": len(body.steps)},
        }

    @app.post("/v1/processes/from-text", tags=["automation"])
    async def process_from_text(body: ProcessNLRequest, request: Request):
        compiled = processes.compile_nl(body)
        record = await db.save_process(request.state.principal.tenant_id, compiled["process"])
        return {**compiled, "process_id": record.id}

    @app.post("/v1/processes", tags=["automation"], status_code=201)
    async def save_process(body: ProcessDefinition, request: Request):
        invalid = processes.validate(body.steps)
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported step types at indexes: {invalid}",
            )
        record = await db.save_process(request.state.principal.tenant_id, body.model_dump())
        return {
            "id": record.id,
            "name": record.name,
            "trigger": record.trigger,
            "definition": record.definition,
            "active": record.active,
        }

    @app.post("/v1/processes/instances", tags=["automation"], status_code=201)
    async def start_process(body: ProcessStartRequest, request: Request):
        principal = request.state.principal
        try:
            instance = await process_engine.start(
                str(body.process_id),
                principal.tenant_id,
                principal.user_id,
                body.context,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Process not found") from error
        except WorkflowConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if instance.status == "waiting":
            process = await db.get_process(str(body.process_id), principal.tenant_id)
            step = process.definition["steps"][instance.current_step] if process else {}
            seconds = max(1, min(int(step.get("seconds", 60)), 86_400))
            celery_app.send_task(
                "orchestra.resume_process_wait",
                args=[instance.id, principal.tenant_id],
                countdown=seconds,
            )
        return process_instance_payload(instance)

    @app.get("/v1/processes/instances/{instance_id}", tags=["automation"])
    async def get_process_instance(instance_id: str, request: Request):
        instance = await db.get_process_instance(instance_id, request.state.principal.tenant_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Process instance not found")
        return process_instance_payload(instance)

    @app.post("/v1/processes/instances/{instance_id}/approve", tags=["automation"])
    async def approve_process(instance_id: str, body: ProcessApprovalRequest, request: Request):
        try:
            instance = await process_engine.approve(
                instance_id,
                request.state.principal.tenant_id,
                body.approved,
                body.comment,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Process instance not found") from error
        except WorkflowConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return process_instance_payload(instance)

    @app.post("/v1/processes/instances/{instance_id}/resume", tags=["automation"])
    async def resume_process(instance_id: str, request: Request):
        try:
            instance = await process_engine.resume_after_action(
                instance_id, request.state.principal.tenant_id
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Process instance not found") from error
        except WorkflowConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return process_instance_payload(instance)

    @app.post("/v1/content/generate", tags=["content"])
    async def generate_content(body: ContentRequest):
        return await content.generate(body)

    @app.post("/v1/content/presentation", tags=["content"])
    async def generate_presentation(body: PresentationRequest):
        file_content = content.presentation(body.title, body.content, body.slides)
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", body.title).strip("-") or "deck"
        return Response(
            file_content,
            media_type=(
                "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            ),
            headers={"content-disposition": f'attachment; filename="{safe_name}.pptx"'},
        )

    @app.post("/v1/training/tests", tags=["training"])
    async def generate_training_test(body: TrainingGenerateRequest):
        return {"questions": training.generate(body.source, body.count)}

    @app.post("/v1/training/evaluate", tags=["training"])
    async def evaluate_training_answer(body: TrainingEvaluateRequest):
        return await training.evaluate(body)

    @app.post("/v1/analytics/process-mining", tags=["analytics"])
    async def process_mining(body: ProcessMiningRequest):
        return analytics.process_mining(body.events)

    @app.post("/v1/analytics/kpi-forecast", tags=["analytics"])
    async def kpi_forecast(body: KPIForecastRequest):
        return analytics.forecast(body)

    @app.post("/v1/projects/digest", tags=["tasks"])
    async def project_digest(body: ProjectDigestRequest):
        return analytics.project_digest(body)

    @app.post("/v1/voice/synthesize", tags=["voice"])
    async def synthesize_speech(body: SpeechRequest):
        try:
            audio_content = await audio.synthesize(body.text, body.voice, body.format)
        except ExternalProviderRequired as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return Response(
            audio_content,
            media_type=f"audio/{body.format}",
            headers={"content-disposition": f'attachment; filename="speech.{body.format}"'},
        )

    @app.post("/v1/bitrix/call", tags=["integrations"])
    async def bitrix_call(body: BitrixCallRequest, request: Request):
        principal = request.state.principal
        try:
            result = await bitrix.call(body.method, body.params)
        except (ValueError, RuntimeError) as error:
            await db.append_event(
                "bitrix.call.failed",
                principal.user_id,
                {"method": body.method, "error": str(error)[:2_000]},
                tenant_id=principal.tenant_id,
            )
            raise HTTPException(status_code=422, detail=str(error)) from error
        await db.append_event(
            "bitrix.call.completed",
            principal.user_id,
            {"method": body.method},
            tenant_id=principal.tenant_id,
        )
        return result

    @app.post("/v1/bitrix/batch", tags=["integrations"])
    async def bitrix_batch(body: list[BitrixCallRequest], request: Request):
        principal = request.state.principal
        try:
            result = await bitrix.batch([(item.method, item.params) for item in body])
        except (ValueError, RuntimeError) as error:
            await db.append_event(
                "bitrix.batch.failed",
                principal.user_id,
                {
                    "methods": [item.method for item in body],
                    "error": str(error)[:2_000],
                },
                tenant_id=principal.tenant_id,
            )
            raise HTTPException(status_code=422, detail=str(error)) from error
        await db.append_event(
            "bitrix.batch.completed",
            principal.user_id,
            {"methods": [item.method for item in body]},
            tenant_id=principal.tenant_id,
        )
        return result

    @app.post("/v1/webhooks/bitrix24", tags=["integrations"])
    async def bitrix_webhook(
        body: WebhookEnvelope,
        x_webhook_secret: Annotated[str | None, Header()] = None,
        x_tenant_id: Annotated[str, Header()] = "default",
    ):
        expected_secret = settings.webhook_secret_map.get(x_tenant_id)
        if expected_secret and not secrets.compare_digest(x_webhook_secret or "", expected_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        if settings.webhook_secret_map and not expected_secret:
            raise HTTPException(status_code=401, detail="Unknown webhook tenant")
        if settings.environment == "production" and not body.event_id:
            raise HTTPException(status_code=422, detail="event_id is required")
        inserted = await db.append_event(
            f"bitrix.{body.event}",
            "bitrix24",
            body.model_dump(mode="json"),
            external_id=(f"bitrix:{x_tenant_id}:{body.event_id}" if body.event_id else None),
            tenant_id=x_tenant_id,
        )
        instances = []
        if inserted:
            for process in await db.processes_for_trigger(body.event, x_tenant_id):
                instance = await process_engine.start(
                    process.id,
                    x_tenant_id,
                    "bitrix24",
                    {"event": body.model_dump(mode="json")},
                )
                instances.append(instance.id)
        return {
            "accepted": inserted,
            "duplicate": not inserted,
            "event_id": body.event_id,
            "process_instances": instances,
        }

    @app.post("/mcp", tags=["mcp"])
    async def mcp(body: MCPRequest, request: Request):
        principal = request.state.principal
        if body.method == "initialize":
            result: Any = {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "ai-orchestra", "version": __version__},
                "capabilities": {"tools": {}},
            }
        elif body.method == "tools/list":
            result = {"tools": MCP_TOOLS}
        elif body.method == "tools/call":
            tool_name = body.params.get("name")
            arguments = body.params.get("arguments", {})
            if tool_name == "orchestra_agent":
                agent_request = AgentRequest(**arguments).model_copy(
                    update={
                        "user_id": principal.user_id,
                        "tenant_id": principal.tenant_id,
                    }
                )
                response = await orchestrator.execute(agent_request)
                result = {"content": [{"type": "text", "text": response.model_dump_json()}]}
            elif tool_name == "knowledge_search":
                answer = await knowledge.answer(
                    arguments["question"],
                    arguments.get("limit", 5),
                    principal.tenant_id,
                )
                result = {"content": [{"type": "text", "text": answer.model_dump_json()}]}
            elif tool_name == "crm_extract":
                extraction = crm.extract(arguments["text"], arguments.get("current_fields", {}))
                result = {"content": [{"type": "text", "text": extraction.model_dump_json()}]}
            elif tool_name == "call_analyze":
                analysis = calls.analyze(arguments["transcript"], arguments.get("sales_script", []))
                result = {"content": [{"type": "text", "text": analysis.model_dump_json()}]}
            elif tool_name == "process_from_text":
                compiled = processes.compile_nl(ProcessNLRequest(**arguments))
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(compiled, ensure_ascii=False),
                        }
                    ]
                }
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": body.id,
                    "error": {"code": -32602, "message": "Unknown tool"},
                }
        else:
            return {
                "jsonrpc": "2.0",
                "id": body.id,
                "error": {"code": -32601, "message": "Method not found"},
            }
        return {"jsonrpc": "2.0", "id": body.id, "result": result}

    return app


app = create_app()
