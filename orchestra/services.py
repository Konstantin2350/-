import hashlib
import io
import math
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from docx import Document as DocxDocument
from pypdf import PdfReader

from orchestra.config import Settings
from orchestra.infrastructure import Database, as_uuid
from orchestra.schemas import (
    CRMEntity,
    CRMExtractResponse,
    CallAnalysis,
    Citation,
    DealHistoryItem,
    KnowledgeAnswer,
    KnowledgeDocumentResponse,
    TaskDraft,
)


TOKEN_RE = re.compile(r"[\wа-яё-]+", re.IGNORECASE)
SEARCH_STOPWORDS = {
    "а", "без", "в", "для", "до", "и", "из", "как", "к", "на", "о", "от",
    "по", "при", "с", "у", "через", "что", "кто", "the", "a", "an", "how",
}


def tokens(text: str) -> list[str]:
    return [word.lower() for word in TOKEN_RE.findall(text)]


def lexical_roots(text: str) -> set[str]:
    """Lightweight language-agnostic roots improve local search without ML models."""
    return {
        word[:5] if len(word) > 6 else word
        for word in tokens(text)
        if word not in SEARCH_STOPWORDS
    }


def focused_excerpt(text: str, query_roots: set[str], limit: int = 500) -> str:
    lowered = text.lower()
    positions = sorted(
        position
        for root in query_roots
        if (position := lowered.find(root)) >= 0
    )
    focus = positions[len(positions) // 2] if positions else 0
    start = max(0, focus - limit // 3)
    if start:
        boundary = text.find(" ", start)
        start = boundary + 1 if boundary >= 0 else start
    excerpt = text[start : start + limit]
    if start + limit < len(text):
        boundary = excerpt.rfind(" ")
        if boundary > limit // 2:
            excerpt = excerpt[:boundary]
    return excerpt.strip()


class LLMClient:
    """OpenAI-compatible LLM client; callers always have deterministic fallbacks."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_api_key)

    async def complete(
        self, system: str, user: str, temperature: float = 0.2
    ) -> str | None:
        if not self.enabled:
            return None
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json={
                    "model": self.settings.llm_model,
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]


class Embeddings:
    """Local hashing embeddings keep RAG operational without an external AI key."""

    dimensions = 256

    def encode(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word, count in Counter(tokens(text)).items():
            digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % self.dimensions
            sign = 1 if digest[0] & 1 else -1
            vector[index] += sign * (1 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector)) or 1
        return [value / norm for value in vector]

    @staticmethod
    def similarity(left: list[float], right: list[float]) -> float:
        return sum(a * b for a, b in zip(left, right, strict=False))


class KnowledgeService:
    supported_extensions = {".pdf", ".docx", ".txt", ".md"}

    def __init__(self, db: Database, settings: Settings, llm: LLMClient) -> None:
        self.db = db
        self.settings = settings
        self.llm = llm
        self.embeddings = Embeddings()

    def extract_text(self, filename: str, content: bytes) -> str:
        extension = Path(filename).suffix.lower()
        if extension not in self.supported_extensions:
            raise ValueError("Supported formats: PDF, DOCX, TXT, MD")
        if extension == ".pdf":
            return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
        if extension == ".docx":
            document = DocxDocument(io.BytesIO(content))
            return "\n".join(paragraph.text for paragraph in document.paragraphs)
        return content.decode("utf-8", errors="replace")

    def chunk(self, text: str) -> list[str]:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return []
        size = self.settings.knowledge_chunk_size
        overlap = min(self.settings.knowledge_chunk_overlap, size // 2)
        chunks: list[str] = []
        start = 0
        while start < len(cleaned):
            end = min(start + size, len(cleaned))
            if end < len(cleaned):
                boundary = cleaned.rfind(" ", start + size // 2, end)
                if boundary > start:
                    end = boundary
            chunks.append(cleaned[start:end].strip())
            if end == len(cleaned):
                break
            candidate = end - overlap
            next_boundary = cleaned.find(" ", candidate, end)
            start = next_boundary + 1 if next_boundary != -1 else end
        return chunks

    async def ingest(
        self, filename: str, content: bytes, title: str | None = None
    ) -> KnowledgeDocumentResponse:
        if len(content) > self.settings.max_upload_bytes:
            raise ValueError("Document exceeds configured upload limit")
        text = self.extract_text(filename, content)
        chunks = self.chunk(text)
        if not chunks:
            raise ValueError("Document contains no readable text")
        document = await self.db.save_document(
            title=title or Path(filename).stem,
            source_name=filename,
            content_hash=hashlib.sha256(content).hexdigest(),
            chunks=[(chunk, self.embeddings.encode(chunk)) for chunk in chunks],
        )
        return KnowledgeDocumentResponse(
            id=as_uuid(document.id),
            title=document.title,
            version=document.version,
            chunks=len(chunks),
            created_at=document.created_at,
        )

    async def search(self, question: str, limit: int = 5) -> list[Citation]:
        query_embedding = self.embeddings.encode(question)
        query_words = lexical_roots(question)
        ranked: list[tuple[float, Any, Any]] = []
        stored = await self.db.all_chunks()
        latest_versions: dict[str, int] = {}
        for _, document in stored:
            latest_versions[document.title] = max(
                latest_versions.get(document.title, 0), document.version
            )
        for chunk, document in stored:
            if document.version != latest_versions[document.title]:
                continue
            semantic = self.embeddings.similarity(query_embedding, chunk.embedding)
            chunk_words = lexical_roots(chunk.text)
            lexical = len(query_words & chunk_words) / max(len(query_words), 1)
            score = 0.35 * max(semantic, 0) + 0.65 * lexical
            ranked.append((score, chunk, document))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            Citation(
                document_id=UUID(document.id),
                title=document.title,
                version=document.version,
                chunk=chunk.position,
                excerpt=focused_excerpt(chunk.text, query_words),
                score=round(score, 4),
            )
            for score, chunk, document in ranked[:limit]
            if score > 0
        ]

    async def answer(self, question: str, limit: int = 5) -> KnowledgeAnswer:
        citations = await self.search(question, limit)
        if not citations:
            return KnowledgeAnswer(
                answer="В базе знаний пока нет подходящей информации.",
                citations=[],
            )
        context = "\n\n".join(
            f"[{index}] {citation.excerpt}"
            for index, citation in enumerate(citations, start=1)
        )
        generated = await self.llm.complete(
            "Отвечай только по контексту. После утверждений ставь номера источников [1].",
            f"Вопрос: {question}\n\nКонтекст:\n{context}",
        )
        answer = generated or (
            f"По базе знаний найдено: {citations[0].excerpt} [1]"
        )
        return KnowledgeAnswer(answer=answer, citations=citations)


class CRMService:
    phone_re = re.compile(r"(?:\+7|8)[\s(.-]*\d{3}[\s).-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}")
    email_re = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Zа-яА-Я]{2,}")
    amount_re = re.compile(
        r"(?:сумм\w*\s*(?:составляет|:)?\s*)?(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(₽|руб(?:лей|ля|ль)?|р\b)",
        re.IGNORECASE,
    )
    name_re = re.compile(
        r"(?:меня зовут|клиент|имя)\s*[:—-]?\s*([А-ЯЁA-Z][а-яёa-z-]{1,30})",
        re.IGNORECASE,
    )
    product_re = re.compile(
        r"(?:интересует|нужен|нужна|заказать|купить)\s+([^.,!?]{2,80})",
        re.IGNORECASE,
    )

    def extract(
        self, text: str, current_fields: dict[str, Any] | None = None
    ) -> CRMExtractResponse:
        current_fields = current_fields or {}
        phone = self.phone_re.search(text)
        email = self.email_re.search(text)
        amount = self.amount_re.search(text)
        name = self.name_re.search(text)
        product = self.product_re.search(text)
        entity = CRMEntity(
            name=name.group(1).title() if name else None,
            phone=re.sub(r"[^\d+]", "", phone.group(0)) if phone else None,
            email=email.group(0).lower() if email else None,
            amount=float(amount.group(1).replace(" ", "").replace(",", ".")) if amount else None,
            product=product.group(1).strip() if product else None,
        )
        found = {key: value for key, value in entity.model_dump().items() if value is not None}
        updates = {key: value for key, value in found.items() if not current_fields.get(key)}
        suggestions = {
            key: value
            for key, value in found.items()
            if current_fields.get(key) not in (None, value)
        }
        lowered = text.lower()
        spam_words = {"ошиблись номером", "не звоните", "реклама казино", "робот обзвон"}
        irrelevant = any(word in lowered for word in spam_words) or len(tokens(text)) < 3
        confidence = min(0.98, 0.35 + len(found) * 0.12 + (0.15 if not irrelevant else 0))
        return CRMExtractResponse(
            entities=entity,
            field_updates=updates,
            suggestions=suggestions,
            relevance="irrelevant" if irrelevant else ("relevant" if found else "uncertain"),
            confidence=round(confidence, 2),
        )

    def score_deal(self, text: str, entities: CRMEntity) -> float:
        positive = {"готов", "купить", "договор", "счет", "оплата", "срок", "бюджет"}
        negative = {"дорого", "подумаю", "отказ", "неинтересно", "позже"}
        words = set(tokens(text))
        score = 0.5 + 0.08 * len(words & positive) - 0.1 * len(words & negative)
        if entities.amount:
            score += 0.08
        if entities.phone or entities.email:
            score += 0.06
        return round(max(0.02, min(0.98, score)), 2)

    def repeat_sales(self, history: list[DealHistoryItem]) -> list[dict[str, Any]]:
        results = []
        for item in history:
            recency = max(0, 100 - item.days_since_last_purchase) / 100
            frequency = min(item.purchases / 10, 1)
            monetary = min(math.log10(max(item.amount, 1)) / 6, 1)
            score = 0.45 * recency + 0.3 * frequency + 0.25 * monetary
            if item.won:
                score += 0.1
            results.append({"customer_id": item.customer_id, "score": round(min(score, 1), 3)})
        return sorted(results, key=lambda item: item["score"], reverse=True)


class CallService:
    positive_words = {"спасибо", "отлично", "подходит", "договорились", "хорошо", "да"}
    negative_words = {"плохо", "дорого", "проблема", "недоволен", "отказ", "нет"}

    def __init__(self, crm: CRMService) -> None:
        self.crm = crm

    def analyze(self, transcript: str, script: list[str]) -> CallAnalysis:
        lowered = transcript.lower()
        word_set = set(tokens(transcript))
        positive = len(word_set & self.positive_words)
        negative = len(word_set & self.negative_words)
        sentiment = "positive" if positive > negative else "negative" if negative > positive else "neutral"
        matched: list[str] = []
        missing: list[str] = []
        for step in script:
            step_words = set(tokens(step))
            overlap = len(step_words & word_set) / max(len(step_words), 1)
            (matched if overlap >= 0.3 else missing).append(step)
        score = len(matched) / len(script) if script else 1.0
        action_items = []
        for sentence in re.split(r"(?<=[.!?])\s+", transcript):
            if re.search(r"\b(нужно|надо|отправ|позвон|подготов|соглас|до\s+\d|завтра)\w*", sentence, re.I):
                action_items.append(sentence.strip())
        crm_result = self.crm.extract(transcript)
        feedback = []
        if missing:
            feedback.append("Добавьте пропущенные этапы скрипта: " + "; ".join(missing))
        if sentiment == "negative":
            feedback.append("Уточните причину недовольства и подтвердите, что услышали клиента.")
        if not action_items:
            feedback.append("Зафиксируйте конкретный следующий шаг и срок.")
        summary_sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", transcript) if part.strip()]
        emotion_signals = [f"Тональность: {sentiment}"]
        if transcript.count("!") >= 2:
            emotion_signals.append("Повышенная эмоциональность")
        if len(tokens(transcript)) > 300:
            emotion_signals.append("Длинный разговор")
        return CallAnalysis(
            summary=" ".join(summary_sentences[:3])[:1000],
            sentiment=sentiment,
            emotion_signals=emotion_signals,
            script_score=round(score, 2),
            matched_steps=matched,
            missing_steps=missing,
            action_items=action_items[:10],
            feedback=feedback,
            relevance=crm_result.relevance if crm_result.relevance != "uncertain" else "relevant",
            crm=crm_result,
        )


class TaskService:
    def create(self, text: str, assignees: list[dict[str, Any]]) -> TaskDraft:
        sentences = [part.strip() for part in re.split(r"[\n.!?]+", text) if part.strip()]
        title = (sentences[0] if sentences else text)[:120]
        deadline = self._deadline(text)
        lowered = text.lower()
        priority = "high" if any(word in lowered for word in ("срочно", "критично", "asap")) else "normal"
        checklist = sentences[1:8] or [
            "Уточнить ожидаемый результат",
            "Выполнить работу",
            "Проверить и сообщить результат",
        ]
        recommended = self._assignee(text, assignees)
        risks = []
        if deadline and any(word in lowered for word in ("сегодня", "срочно")):
            risks.append("Короткий срок исполнения")
        if len(checklist) > 6:
            risks.append("Задачу стоит разделить на подзадачи")
        if not recommended and assignees:
            risks.append("Не найден исполнитель с подходящей компетенцией")
        return TaskDraft(
            title=title,
            description=text,
            deadline=deadline,
            priority=priority,
            checklist=checklist,
            recommended_assignee=recommended,
            risk_flags=risks,
        )

    @staticmethod
    def _deadline(text: str) -> str | None:
        lowered = text.lower()
        today = datetime.now(UTC).date()
        if "сегодня" in lowered:
            return today.isoformat()
        if "завтра" in lowered:
            return (today + timedelta(days=1)).isoformat()
        match = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", text)
        if match:
            day, month, year = match.groups()
            normalized_year = int(year) if year else today.year
            if normalized_year < 100:
                normalized_year += 2000
            try:
                return datetime(normalized_year, int(month), int(day)).date().isoformat()
            except ValueError:
                return None
        return None

    @staticmethod
    def _assignee(text: str, assignees: list[dict[str, Any]]) -> str | None:
        words = set(tokens(text))
        ranked = []
        for person in assignees:
            skills = set(tokens(" ".join(person.get("skills", []))))
            skill_match = len(words & skills)
            load = float(person.get("load", 0))
            ranked.append((skill_match - load / 100, person.get("name")))
        ranked.sort(reverse=True)
        return ranked[0][1] if ranked and ranked[0][1] else None
