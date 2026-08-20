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
from fastapi.responses import JSONResponse
from sqlalchemy import text

from orchestra import __version__
from orchestra.agents import build_orchestrator
from orchestra.config import Settings, get_settings
from orchestra.infrastructure import ConversationMemory, Database
from orchestra.integrations import MCP_TOOLS, Bitrix24Client
from orchestra.schemas import (
    AgentRequest,
    BitrixCallRequest,
    CallAnalyzeRequest,
    ChatRequest,
    CRMExtractRequest,
    DealHistoryItem,
    KnowledgeQuery,
    MCPRequest,
    ProcessDefinition,
    TaskCreateRequest,
    WebhookEnvelope,
)
from orchestra.worker import celery_app


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = Database(settings)
    memory = ConversationMemory(settings)
    orchestrator, knowledge, crm, calls, tasks = build_orchestrator(
        settings, db, memory
    )
    bitrix = Bitrix24Client(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await db.create_schema()
        yield
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

    @app.middleware("http")
    async def security_and_trace(request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid4()))
        public_paths = {"/health", "/ready", "/docs", "/openapi.json", "/redoc"}
        is_webhook = request.url.path.startswith("/v1/webhooks/")
        if (
            settings.api_key
            and request.url.path not in public_paths
            and not is_webhook
            and not secrets.compare_digest(
                request.headers.get("x-api-key", ""), settings.api_key
            )
        ):
            return JSONResponse(
                {"detail": "Invalid API key", "request_id": request_id},
                status_code=401,
            )
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
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
        try:
            async with db.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as error:
            raise HTTPException(status_code=503, detail="Database unavailable") from error
        return {"status": "ready"}

    @app.post("/v1/orchestrate", tags=["agents"])
    async def orchestrate(body: AgentRequest):
        return await orchestrator.execute(body)

    @app.post("/v1/jobs/agent", tags=["agents"], status_code=202)
    async def enqueue_agent(body: AgentRequest):
        try:
            job = celery_app.send_task(
                "orchestra.run_agent", args=[body.model_dump(mode="json")]
            )
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

    @app.post("/v1/calls/analyze", tags=["calls"])
    async def analyze_call(body: CallAnalyzeRequest):
        return calls.analyze(body.transcript, body.sales_script)

    @app.post("/v1/chat/messages", tags=["chat"])
    async def chat(body: ChatRequest):
        return await orchestrator.chat(body)

    @app.websocket("/v1/chat/ws/{session_id}")
    async def chat_socket(websocket: WebSocket, session_id: str):
        supplied_key = websocket.query_params.get("api_key", "")
        if settings.api_key and not secrets.compare_digest(
            supplied_key, settings.api_key
        ):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
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
        allowed = {"agent", "bitrix_call", "condition", "wait", "notify", "human_approval"}
        invalid = [
            index
            for index, step in enumerate(body.steps)
            if step.get("type") not in allowed
        ]
        if invalid:
            raise HTTPException(
                status_code=422, detail=f"Unsupported step types at indexes: {invalid}"
            )
        return {
            "dsl_version": "1.0",
            "process": body.model_dump(),
            "validation": {"valid": True, "steps": len(body.steps)},
        }

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
        await db.append_event(
            f"bitrix.{body.event}", "bitrix24", body.model_dump(mode="json")
        )
        return {"accepted": True, "event_id": body.event_id}

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
                result = {
                    "content": [
                        {"type": "text", "text": response.model_dump_json()}
                    ]
                }
            elif tool_name == "knowledge_search":
                answer = await knowledge.answer(
                    arguments["question"], arguments.get("limit", 5)
                )
                result = {
                    "content": [{"type": "text", "text": answer.model_dump_json()}]
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
