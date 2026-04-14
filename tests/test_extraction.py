import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.lead import LeadIntent
from app.services.extraction import (
    _fallback_extraction,
    _parse_llm_response,
    extract_lead_data,
)


def test_fallback_extraction_maps_known_keys():
    payload = {
        "name": "Alice Smith",
        "email": "alice@bigco.com",
        "company": "BigCo",
        "phone": "+1555999000",
        "job_title": "VP Engineering",
    }
    result = _fallback_extraction(payload)
    assert result.name == "Alice Smith"
    assert result.email == "alice@bigco.com"
    assert result.company == "BigCo"
    assert result.title == "VP Engineering"
    assert result.intent == LeadIntent.UNKNOWN
    assert result.confidence_score == 0.3


def test_fallback_extraction_handles_missing_keys():
    result = _fallback_extraction({"random_field": "value"})
    assert result.name is None
    assert result.email is None
    assert result.confidence_score == 0.3


def test_parse_llm_response_clean_json():
    raw = json.dumps({
        "name": "Jane Doe",
        "email": "jane@acme.com",
        "company": "Acme Inc",
        "phone": "+15551234567",
        "title": "Director of Sales",
        "intent": "demo_request",
        "confidence_score": 0.92,
    })
    result = _parse_llm_response(raw)
    assert result.name == "Jane Doe"
    assert result.intent == LeadIntent.DEMO_REQUEST
    assert result.confidence_score == 0.92


def test_parse_llm_response_with_markdown_fences():
    raw = '```json\n{"name": "Bob", "intent": "support", "confidence_score": 0.7}\n```'
    result = _parse_llm_response(raw)
    assert result.name == "Bob"
    assert result.intent == LeadIntent.SUPPORT
    assert result.confidence_score == 0.7


def test_parse_llm_response_invalid_json():
    result = _parse_llm_response("This is not JSON at all")
    assert result.intent == LeadIntent.UNKNOWN
    assert result.confidence_score == 0.2


def test_parse_llm_response_unknown_intent():
    raw = json.dumps(
        {"name": "Test", "intent": "buy_now", "confidence_score": 0.5})
    result = _parse_llm_response(raw)
    assert result.intent == LeadIntent.UNKNOWN


@pytest.mark.asyncio
async def test_extract_falls_back_without_api_key():
    with patch("app.services.extraction.settings") as mock_settings:
        mock_settings.openrouter_api_key = ""
        mock_settings.openrouter_base_url = "https://openrouter.ai/api/v1"
        mock_settings.openrouter_model = "meta-llama/llama-3.1-8b-instruct:free"
        mock_settings.llm_timeout_seconds = 30

        result = await extract_lead_data(
            {"name": "Bob", "email": "bob@test.com"}
        )
        assert result.name == "Bob"
        assert result.confidence_score == 0.3


@pytest.mark.asyncio
async def test_extract_with_mocked_openrouter():
    llm_json = json.dumps({
        "name": "Jane Doe",
        "email": "jane@acme.com",
        "company": "Acme Inc",
        "phone": "+15551234567",
        "title": "Director of Sales",
        "intent": "demo_request",
        "confidence_score": 0.92,
    })

    mock_message = MagicMock()
    mock_message.content = llm_json
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch("app.services.extraction.settings") as mock_settings:
        mock_settings.openrouter_api_key = "sk-or-test"
        mock_settings.openrouter_base_url = "https://openrouter.ai/api/v1"
        mock_settings.openrouter_model = "meta-llama/llama-3.1-8b-instruct:free"
        mock_settings.llm_timeout_seconds = 30

        with patch("app.services.extraction.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_cls.return_value = mock_client

            result = await extract_lead_data(
                {"message": "I'd like a demo of your product"}
            )

    assert result.name == "Jane Doe"
    assert result.intent == LeadIntent.DEMO_REQUEST
    assert result.confidence_score == 0.92
