import json

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.logging import get_logger
from app.models.lead import LeadIntent

logger = get_logger(__name__)


class ExtractedLead(BaseModel):
    """Structured lead data extracted from raw input."""

    name: str | None = Field(None, description="Full name of the contact")
    email: str | None = Field(None, description="Email address")
    company: str | None = Field(
        None, description="Company or organization name"
    )
    phone: str | None = Field(None, description="Phone number")
    title: str | None = Field(None, description="Job title or role")
    intent: LeadIntent = Field(
        LeadIntent.UNKNOWN,
        description="Classified intent of the lead",
    )
    confidence_score: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Confidence in extraction quality (0.0 to 1.0)",
    )


EXTRACTION_PROMPT = (
    "You are a lead data extraction system. Given raw lead data "
    "(which may come from a web form, email, or CSV row), extract "
    "structured fields and respond with ONLY valid JSON.\n\n"
    "Classify the intent as one of: demo_request, pricing_inquiry, "
    "support, partnership, general_inquiry, unknown.\n\n"
    "Set confidence_score between 0.0 and 1.0:\n"
    "- 1.0: all fields clearly present\n"
    "- 0.7-0.9: most fields present, some inference\n"
    "- 0.4-0.6: significant inference or missing fields\n"
    "- below 0.4: very uncertain\n\n"
    "Respond with this exact JSON schema:\n"
    '{{\n'
    '  "name": "string or null",\n'
    '  "email": "string or null",\n'
    '  "company": "string or null",\n'
    '  "phone": "string or null",\n'
    '  "title": "string or null",\n'
    '  "intent": "one of the intent values above",\n'
    '  "confidence_score": 0.0\n'
    '}}\n\n'
    "Raw lead data:\n{raw_data}"
)


async def extract_lead_data(raw_payload: dict) -> ExtractedLead:
    if not settings.openrouter_api_key:
        logger.warning(
            "openrouter_api_key_missing",
            msg="Falling back to passthrough extraction",
        )
        return _fallback_extraction(raw_payload)

    try:
        client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )
        response = await client.chat.completions.create(
            model=settings.openrouter_model,
            messages=[
                {
                    "role": "user",
                    "content": EXTRACTION_PROMPT.format(
                        raw_data=str(raw_payload)
                    ),
                }
            ],
            timeout=settings.llm_timeout_seconds,
        )

        raw_text = response.choices[0].message.content or ""
        result = _parse_llm_response(raw_text)
        logger.info(
            "extraction_complete",
            confidence=result.confidence_score,
            intent=result.intent.value,
            model=settings.openrouter_model,
        )
        return result
    except Exception as e:
        logger.error("extraction_failed", error=str(e))
        return _fallback_extraction(raw_payload)


def _parse_llm_response(raw_text: str) -> ExtractedLead:
    """Parse JSON from LLM response, tolerating markdown fences."""
    text = raw_text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
        # Validate intent is a known value
        intent_str = data.get("intent", "unknown")
        try:
            intent = LeadIntent(intent_str)
        except ValueError:
            intent = LeadIntent.UNKNOWN

        return ExtractedLead(
            name=data.get("name"),
            email=data.get("email"),
            company=data.get("company"),
            phone=data.get("phone"),
            title=data.get("title"),
            intent=intent,
            confidence_score=float(data.get("confidence_score", 0.5)),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("llm_json_parse_failed",
                       error=str(e), raw=raw_text[:200])
        return ExtractedLead(intent=LeadIntent.UNKNOWN, confidence_score=0.2)


def _fallback_extraction(raw_payload: dict) -> ExtractedLead:
    """Best-effort extraction without LLM — just maps known keys."""
    return ExtractedLead(
        name=raw_payload.get("name"),
        email=raw_payload.get("email"),
        company=raw_payload.get("company"),
        phone=raw_payload.get("phone"),
        title=raw_payload.get("title") or raw_payload.get("job_title"),
        intent=LeadIntent.UNKNOWN,
        confidence_score=0.3,
    )
