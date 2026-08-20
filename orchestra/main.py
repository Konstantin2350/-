import json
import re
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Any
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
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from orchestra import __version__
from orchestra.agents import build_orchestrator
from orchestra.capabilities import (
    AnalyticsService,
    AudioService,
    ContentService,
    ExternalProviderRequired,
    ProcessService,
    TrainingService,
)
from orchestra.config import Settings, get_settings
from orchestra.infrastructure import ConversationMemory, Database
from orchestra.integrations import MCP_TOOLS, Bitrix24Client
from orchestra.observability import AGENT_RUNS, metrics_middleware, metrics_response
from orchestra.schemas import (
    AgentRequest,
    BitrixCallRequest,
    CallAnalyzeRequest,
    ChatRequest,
    ContentRequest,
    CRMExtractRequest,
    DealModelTrainRequest,
    DealPredictRequest,
    DealHistoryItem,
    KPIForecastRequest,
    KnowledgeQuery,
    MCPRequest,
    ProcessDefinition,
    ProcessMiningRequest,
    ProcessNLRequest,
    PresentationRequest,
    ProjectDigestRequest,
    SpeechRequest,
    TaskCreateRequest,
    TrainingEvaluateRequest,
    TrainingGenerateRequest,
    WebhookEnvelope,
)
from orchestra.security import Authenticator, RateLimiter, ROLE_LEVELS
from orchestra.worker import celery_app


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = Database(settings)
    memory = ConversationMemory(settings)
    orchestrator, knowledge, crm, calls, tasks = build_orchestrator(settings, db, memory)
    bitrix = Bitrix24Client(settings)
    authenticator = Authenticator(settings)
    rate_limiter = RateLimiter(settings)
    audio = AudioService(settings)
    processes = ProcessService()
    content = ContentService(orchestrator.llm)
    training = TrainingService(knowledge.embeddings)
    analytics = AnalyticsService()

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
    )
    app.state.settings = settings
    app.state.db = db
    app.state.orchestrator = orchestrator

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
        principal = authenticator.from_request(request)
        if request.url.path not in public_paths and not is_webhook and not principal:
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
                    "/v1/analytics",
                    "/v1/crm/deal-model",
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
            allowed, remaining = await rate_limiter.allow(principal.user_id)
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
    async def ready() -> dict[str, str]:
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
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return metrics_response()

    @app.post("/v1/orchestrate", tags=["agents"])
    async def orchestrate(body: AgentRequest):
        response = await orchestrator.execute(body)
        AGENT_RUNS.labels(response.agent, str(response.requires_human).lower()).inc()
        return response

    @app.post("/v1/jobs/agent", tags=["agents"], status_code=202)
    async def enqueue_agent(body: AgentRequest):
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

    @app.post("/v1/crm/extract", tags=["crm"])
    async def crm_extract(body: CRMExtractRequest):
        return crm.extract(body.text, body.current_fields)

    @app.post("/v1/crm/repeat-sales", tags=["crm"])
    async def crm_repeat_sales(body: list[DealHistoryItem]):
        return {"customers": crm.repeat_sales(body)}

    @app.post("/v1/crm/deal-model/train", tags=["crm"])
    async def train_deal_model(body: DealModelTrainRequest):
        try:
            parameters, model_metrics = crm.train_deal_model(body.examples)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        model = await db.save_model("deal_outcome", parameters, model_metrics)
        return {
            "model_id": model.id,
            "version": model.version,
            "metrics": model.metrics,
        }

    @app.post("/v1/crm/deal-model/predict", tags=["crm"])
    async def predict_deal(body: DealPredictRequest):
        model = await db.active_model("deal_outcome")
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
    async def chat(body: ChatRequest):
        return await orchestrator.chat(body)

    @app.post("/v1/channels/{channel}/messages", tags=["chat"])
    async def channel_message(channel: str, body: ChatRequest):
        supported = {"web", "bitrix24", "telegram", "whatsapp", "email", "api"}
        if channel not in supported:
            raise HTTPException(status_code=422, detail="Unsupported channel")
        return await orchestrator.chat(body.model_copy(update={"channel": channel}))

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
                allowed, _ = await rate_limiter.allow(principal.user_id)
                if not allowed:
                    await websocket.send_json({"error": "Rate limit exceeded"})
                    await websocket.close(code=1013)
                    return
                payload = await websocket.receive_json()
                response = await orchestrator.chat(
                    ChatRequest(
                        session_id=session_id,
                        message=payload.get("message", ""),
                        user_id=payload.get("user_id", "anonymous"),
                        persona=payload.get("persona", "auto"),
                    )
                )
                await websocket.send_json(response.model_dump(mode="json"))
        except WebSocketDisconnect:
            return

    @app.post("/v1/knowledge/documents", tags=["knowledge"])
    async def upload_document(
        file: Annotated[UploadFile, File()],
        title: Annotated[str | None, Form()] = None,
    ):
        content = await file.read(settings.max_upload_bytes + 1)
        try:
            return await knowledge.ingest(file.filename or "document.txt", content, title)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/knowledge/query", tags=["knowledge"])
    async def query_knowledge(body: KnowledgeQuery):
        return await knowledge.answer(body.question, body.limit)

    @app.post("/v1/tasks/from-text", tags=["tasks"])
    async def task_from_text(body: TaskCreateRequest):
        return tasks.create(body.text, body.available_assignees)

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
    async def process_from_text(body: ProcessNLRequest):
        return processes.compile_nl(body)

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
    async def bitrix_call(body: BitrixCallRequest):
        try:
            return await bitrix.call(body.method, body.params)
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/bitrix/batch", tags=["integrations"])
    async def bitrix_batch(body: list[BitrixCallRequest]):
        try:
            return await bitrix.batch([(item.method, item.params) for item in body])
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/webhooks/bitrix24", tags=["integrations"])
    async def bitrix_webhook(
        body: WebhookEnvelope,
        x_webhook_secret: Annotated[str | None, Header()] = None,
    ):
        if settings.webhook_secret and not secrets.compare_digest(
            x_webhook_secret or "", settings.webhook_secret
        ):
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        inserted = await db.append_event(
            f"bitrix.{body.event}",
            "bitrix24",
            body.model_dump(mode="json"),
            external_id=(f"bitrix:{body.event_id}" if body.event_id else None),
        )
        return {
            "accepted": inserted,
            "duplicate": not inserted,
            "event_id": body.event_id,
        }

    @app.post("/mcp", tags=["mcp"])
    async def mcp(body: MCPRequest):
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
                response = await orchestrator.execute(AgentRequest(**arguments))
                result = {"content": [{"type": "text", "text": response.model_dump_json()}]}
            elif tool_name == "knowledge_search":
                answer = await knowledge.answer(arguments["question"], arguments.get("limit", 5))
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
