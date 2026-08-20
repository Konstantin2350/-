from typing import Any

from orchestra.config import Settings
from orchestra.infrastructure import ConversationMemory, Database
from orchestra.schemas import (
    AgentName,
    AgentRequest,
    AgentResponse,
    ChatRequest,
    ChatResponse,
    TaskCreateRequest,
)
from orchestra.services import (
    CRMService,
    CallService,
    KnowledgeService,
    LLMClient,
    TaskService,
)


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        memory: ConversationMemory,
        llm: LLMClient,
        knowledge: KnowledgeService,
        crm: CRMService,
        calls: CallService,
        tasks: TaskService,
    ) -> None:
        self.settings = settings
        self.db = db
        self.memory = memory
        self.llm = llm
        self.knowledge = knowledge
        self.crm = crm
        self.calls = calls
        self.tasks = tasks

    def route(self, message: str, requested: AgentName | None = None) -> AgentName:
        if requested:
            return requested
        text = message.lower()
        rules: list[tuple[AgentName, tuple[str, ...]]] = [
            ("calls", ("звонок", "разговор", "скрипт продаж", "транскрипт")),
            ("crm", ("сделк", "лид", "клиент", "crm", "повторн")),
            ("tasks", ("задач", "поруч", "дедлайн", "чек-лист", "проект")),
            ("knowledge", ("база знаний", "документ", "инструкц", "регламент")),
            ("content", ("напиши", "письмо", "описание", "meta", "презентац")),
            ("chat", ("поддерж", "оператор", "онбординг", "консультац")),
        ]
        scores = {
            agent: sum(keyword in text for keyword in keywords)
            for agent, keywords in rules
        }
        winner = max(scores, key=scores.get)
        return winner if scores[winner] else "chat"

    async def execute(self, request: AgentRequest) -> AgentResponse:
        agent = self.route(request.message, request.agent)
        handlers = {
            "crm": self._crm,
            "calls": self._calls,
            "chat": self._chat,
            "knowledge": self._knowledge,
            "tasks": self._tasks,
            "content": self._content,
        }
        response = await handlers[agent](request)
        await self.db.append_event(
            "agent.completed",
            request.user_id,
            {
                "request_id": str(response.request_id),
                "agent": response.agent,
                "session_id": request.session_id,
                "actions": response.actions,
            },
        )
        return response

    async def _crm(self, request: AgentRequest) -> AgentResponse:
        extraction = self.crm.extract(
            request.message, request.context.get("current_fields", {})
        )
        probability = self.crm.score_deal(request.message, extraction.entities)
        return AgentResponse(
            agent="crm",
            answer="Данные клиента извлечены. Изменения существующих полей вынесены на подтверждение.",
            data={
                "extraction": extraction.model_dump(),
                "deal_probability": probability,
            },
            actions=[
                {
                    "tool": "bitrix.crm.update",
                    "status": "proposed",
                    "requires_confirmation": bool(extraction.suggestions),
                    "fields": extraction.field_updates,
                }
            ],
        )

    async def _calls(self, request: AgentRequest) -> AgentResponse:
        analysis = self.calls.analyze(
            request.message, request.context.get("sales_script", [])
        )
        return AgentResponse(
            agent="calls",
            answer="Звонок разобран: сформированы резюме, оценка скрипта и следующие шаги.",
            data=analysis.model_dump(),
            actions=[
                {"tool": "bitrix.timeline.add", "status": "proposed"},
                {"tool": "bitrix.activity.create", "status": "proposed", "items": analysis.action_items},
            ],
            requires_human=analysis.relevance == "irrelevant",
        )

    async def _knowledge(self, request: AgentRequest) -> AgentResponse:
        result = await self.knowledge.answer(request.message)
        return AgentResponse(
            agent="knowledge",
            answer=result.answer,
            citations=result.citations,
        )

    async def _tasks(self, request: AgentRequest) -> AgentResponse:
        draft = self.tasks.create(
            request.message, request.context.get("available_assignees", [])
        )
        return AgentResponse(
            agent="tasks",
            answer="Подготовлен проект задачи с чек-листом, исполнителем и рисками.",
            data=draft.model_dump(),
            actions=[
                {
                    "tool": "bitrix.tasks.create",
                    "status": "proposed",
                    "requires_confirmation": True,
                }
            ],
        )

    async def _content(self, request: AgentRequest) -> AgentResponse:
        generated = await self.llm.complete(
            "Ты бизнес-редактор. Пиши конкретно, без выдуманных фактов.",
            request.message,
            temperature=0.5,
        )
        if not generated:
            generated = (
                "Черновик\n\n"
                f"Цель: {request.message.strip()}\n"
                "Ключевая ценность: опишите измеримый результат для клиента.\n"
                "Следующий шаг: предложите конкретное действие и срок."
            )
        return AgentResponse(agent="content", answer=generated)

    async def _chat(self, request: AgentRequest) -> AgentResponse:
        result = await self.chat(
            ChatRequest(
                session_id=request.session_id,
                message=request.message,
                user_id=request.user_id,
                persona=request.context.get("persona", "auto"),
            )
        )
        return AgentResponse(
            agent="chat",
            answer=result.answer,
            citations=result.citations,
            data={"persona": result.persona, "history": result.history},
            requires_human=result.handoff,
            actions=(
                [{"tool": "operator.handoff", "reason": result.handoff_reason}]
                if result.handoff
                else []
            ),
        )

    async def chat(self, request: ChatRequest) -> ChatResponse:
        persona = self._persona(request.message, request.persona)
        await self.memory.add(request.session_id, "user", request.message)
        history = await self.memory.history(request.session_id)
        handoff_words = ("оператор", "человек", "жалоба", "претензия", "не помог")
        handoff = any(word in request.message.lower() for word in handoff_words)
        citations = await self.knowledge.search(request.message, 3)
        context = "\n".join(citation.excerpt for citation in citations)
        generated = None
        if not handoff:
            generated = await self.llm.complete(
                f"Ты агент роли {persona}. Используй историю и базу знаний. Не выдумывай факты.",
                f"История: {history[-10:]}\nБаза знаний: {context}\nЗапрос: {request.message}",
            )
        if handoff:
            answer = "Передаю диалог оператору вместе с полной историей."
        elif generated:
            answer = generated
        elif citations:
            answer = f"По базе знаний: {citations[0].excerpt} [1]"
        else:
            answer = self._fallback_answer(persona)
        await self.memory.add(request.session_id, "assistant", answer)
        complete_history = await self.memory.history(request.session_id)
        return ChatResponse(
            answer=answer,
            persona=persona,
            history=complete_history,
            citations=citations,
            handoff=handoff,
            handoff_reason="Клиент запросил человека или сообщил о проблеме" if handoff else None,
        )

    @staticmethod
    def _persona(message: str, requested: str) -> str:
        if requested != "auto":
            return requested
        lowered = message.lower()
        if any(word in lowered for word in ("купить", "цена", "тариф", "демо")):
            return "sales"
        if any(word in lowered for word in ("начать", "настроить", "обучение")):
            return "onboarding"
        return "support"

    @staticmethod
    def _fallback_answer(persona: str) -> str:
        prompts: dict[str, str] = {
            "sales": "Уточните задачу, бюджет и желаемый срок — я предложу подходящий вариант.",
            "onboarding": "Опишите текущий этап настройки — я дам следующий шаг.",
            "support": "Опишите проблему и ожидаемый результат, чтобы я помог точнее.",
        }
        return prompts[persona]


def build_orchestrator(
    settings: Settings, db: Database, memory: ConversationMemory
) -> tuple[Orchestrator, KnowledgeService, CRMService, CallService, TaskService]:
    llm = LLMClient(settings)
    crm = CRMService()
    calls = CallService(crm)
    tasks = TaskService()
    knowledge = KnowledgeService(db, settings, llm)
    return (
        Orchestrator(settings, db, memory, llm, knowledge, crm, calls, tasks),
        knowledge,
        crm,
        calls,
        tasks,
    )
