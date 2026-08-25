import json
import re
from pathlib import Path
from urllib.parse import quote

from orchestra.config import Settings
from orchestra.schemas import CampaignConfig


class CampaignRegistry:
    """Loads trackable lead campaigns without depending on an external CRM."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        path = Path(settings.campaign_config_path)
        if not path.exists():
            self._campaigns: dict[str, CampaignConfig] = {}
            return
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else raw.get("campaigns", [])
        campaigns = [CampaignConfig.model_validate(item) for item in items]
        self._campaigns = {campaign.code: campaign for campaign in campaigns}

    def list(self, tenant_id: str) -> list[CampaignConfig]:
        return [item for item in self._campaigns.values() if item.tenant_id == tenant_id]

    def get(self, code: str, tenant_id: str | None = None) -> CampaignConfig | None:
        campaign = self._campaigns.get(code)
        if campaign and (tenant_id is None or campaign.tenant_id == tenant_id):
            return campaign
        return None

    def public_link(self, campaign: CampaignConfig, channel: str | None = None) -> str:
        suffix = f"/{channel}" if channel else ""
        return f"{self.settings.public_base_url.rstrip('/')}/r/{campaign.code}{suffix}"

    def destination_url(self, campaign: CampaignConfig, channel: str | None = None) -> str:
        resolved_channel = channel or campaign.channel
        if resolved_channel not in campaign.channels:
            raise ValueError(f"Channel {resolved_channel} is not enabled for this campaign")
        if resolved_channel == "whatsapp":
            phone = re.sub(r"\D", "", self.settings.blogger_contact_phone or "")
            if not phone:
                raise ValueError("BLOGGER_CONTACT_PHONE is not configured")
            return f"https://wa.me/{phone}?text={quote(campaign.prefilled_message)}"
        if resolved_channel == "telegram":
            username = (self.settings.blogger_telegram_username or "").removeprefix("@")
            if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
                raise ValueError("BLOGGER_TELEGRAM_USERNAME is not configured")
            return f"https://t.me/{username}?text={quote(campaign.prefilled_message)}"
        raise ValueError(f"Public redirect for {resolved_channel} is not configured")


class LeadQualifier:
    hot_words = (
        "готов купить",
        "хочу посмотреть",
        "запишите на просмотр",
        "ипотека одобрена",
        "наличные",
        "в ближайшее время",
    )

    @staticmethod
    def normalize_phone(phone: str | None) -> str | None:
        if not phone:
            return None
        digits = re.sub(r"\D", "", phone)
        if len(digits) == 11 and digits.startswith("8"):
            digits = "7" + digits[1:]
        if not 10 <= len(digits) <= 15:
            return None
        return f"+{digits}"

    @staticmethod
    def extract_name(message: str) -> str | None:
        match = re.search(
            r"\b(?:меня\s+зовут|я)\s+([а-яёa-z][а-яёa-z-]{1,49})\b",
            message,
            re.IGNORECASE,
        )
        return match.group(1).capitalize() if match else None

    def evaluate(
        self,
        campaign: CampaignConfig,
        message: str,
        name: str | None,
        phone: str | None,
        answers: dict[str, str],
    ) -> dict[str, object]:
        missing = [
            key for key in campaign.qualification_questions if not str(answers.get(key, "")).strip()
        ]
        contact_points = 20 if phone else 0
        answer_points = round(
            60
            * (len(campaign.qualification_questions) - len(missing))
            / len(campaign.qualification_questions)
        )
        intent_points = 20 if any(word in message.lower() for word in self.hot_words) else 0
        score = min(100, contact_points + answer_points + intent_points)
        priority = "hot" if intent_points or score >= 80 else "warm" if score >= 40 else "new"
        status = (
            "qualified" if phone and not missing else "qualifying" if phone or answers else "new"
        )
        next_question = campaign.qualification_questions[missing[0]] if missing else None
        if next_question:
            reply = f"Спасибо! Чтобы помочь по квартире, уточните: {next_question}"
        else:
            reply = (
                f"Спасибо! Заявка по квартире принята. "
                f"Человек подключится в течение {campaign.response_sla_minutes} минут."
            )
        return {
            "name": name,
            "phone": phone,
            "answers": answers,
            "qualification_score": score,
            "priority": priority,
            "status": status,
            "next_question": next_question,
            "reply": reply,
            "handoff_required": bool(phone),
        }
