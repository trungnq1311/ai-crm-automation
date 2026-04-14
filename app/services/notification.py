import httpx

from app.config import settings
from app.logging import get_logger
from app.models.lead import Lead

logger = get_logger(__name__)


async def send_slack_notification(lead: Lead, event: str = "new_lead") -> bool:
    if not settings.slack_webhook_url:
        logger.warning("slack_webhook_missing",
                       msg="Skipping Slack notification")
        return False

    intent_display = lead.intent.value if hasattr(
        lead.intent, "value") else lead.intent
    status_display = lead.status.value if hasattr(
        lead.status, "value") else lead.status

    if event == "new_lead":
        text = (
            f"*New Lead Synced to CRM*\n"
            f"- *Name:* {lead.name or 'N/A'}\n"
            f"- *Email:* {lead.email or 'N/A'}\n"
            f"- *Company:* {lead.company or 'N/A'}\n"
            f"- *Intent:* {intent_display}\n"
            f"- *Score:* {lead.score}/100\n"
            f"- *Confidence:* {lead.confidence_score:.0%}\n"
            f"- *Status:* {status_display}"
        )
    elif event == "needs_review":
        text = (
            f"*Lead Needs Review* (low confidence: {lead.confidence_score:.0%})\n"
            f"- *Name:* {lead.name or 'N/A'}\n"
            f"- *Email:* {lead.email or 'N/A'}\n"
            f"- *Company:* {lead.company or 'N/A'}"
        )
    elif event == "failed":
        text = (
            f"*Lead Processing Failed*\n"
            f"- *Lead ID:* {lead.id}\n"
            f"- *Name:* {lead.name or 'N/A'}\n"
            f"- *Email:* {lead.email or 'N/A'}"
        )
    else:
        text = f"Lead event: {event} for {lead.name or lead.email or lead.id}"

    payload = {"text": text}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.slack_webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("slack_notification_sent",
                        lead_id=str(lead.id), event=event)
            return True
    except Exception as e:
        logger.error("slack_notification_failed",
                     lead_id=str(lead.id), error=str(e))
        return False
