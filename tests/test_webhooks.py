import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.config import settings


@pytest.mark.asyncio
async def test_webhook_receives_lead(client: AsyncClient):
    with patch("app.api.webhooks.redis.from_url") as mock_redis_cls:
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_redis.setex.return_value = True
        mock_redis.aclose.return_value = None
        mock_redis_cls.return_value = mock_redis

        with patch("app.api.webhooks.process_lead_pipeline") as mock_task:
            mock_task.delay.return_value = None

            resp = await client.post(
                "/webhooks/lead",
                json={"source": "web_form", "data": {
                    "name": "Jane Doe", "email": "jane@acme.com"}},
                headers={
                    "X-API-Key": settings.api_key,
                    "X-Idempotency-Key": str(uuid.uuid4()),
                },
            )

    assert resp.status_code == 202
    body = resp.json()
    assert body["source"] == "web_form"
    assert body["status"] == "new"
    assert body["raw_payload"]["name"] == "Jane Doe"


@pytest.mark.asyncio
async def test_webhook_rejects_bad_api_key(client: AsyncClient):
    resp = await client.post(
        "/webhooks/lead",
        json={"source": "web_form", "data": {"name": "Jane Doe"}},
        headers={
            "X-API-Key": "wrong-key",
            "X-Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_webhook_rejects_missing_idempotency_key(client: AsyncClient):
    resp = await client.post(
        "/webhooks/lead",
        json={"source": "web_form", "data": {"name": "Jane Doe"}},
        headers={"X-API-Key": settings.api_key},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_webhook_duplicate_idempotency_key(client: AsyncClient):
    idem_key = str(uuid.uuid4())

    with patch("app.api.webhooks.redis.from_url") as mock_redis_cls:
        mock_redis = AsyncMock()
        mock_redis.get.return_value = b"some-lead-id"
        mock_redis.aclose.return_value = None
        mock_redis_cls.return_value = mock_redis

        resp = await client.post(
            "/webhooks/lead",
            json={"source": "web_form", "data": {"name": "Jane Doe"}},
            headers={
                "X-API-Key": settings.api_key,
                "X-Idempotency-Key": idem_key,
            },
        )

    assert resp.status_code == 409
