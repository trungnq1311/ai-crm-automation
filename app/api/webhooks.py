
import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key, verify_idempotency_key
from app.config import settings
from app.database import get_db
from app.logging import get_logger
from app.models.lead import Lead, LeadStatus
from app.schemas.lead import LeadResponse, WebhookLeadPayload
from app.workers.tasks import process_lead_pipeline

router = APIRouter()
logger = get_logger(__name__)
limiter = Limiter(key_func=get_remote_address)


@router.post("/lead", response_model=LeadResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.webhook_rate_limit)
async def receive_lead(
    request: Request,
    body: WebhookLeadPayload,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
    idempotency_key: str = Depends(verify_idempotency_key),
):
    # Check idempotency
    redis_client = redis.from_url(settings.redis_url)
    cache_key = f"idempotency:{idempotency_key}"
    try:
        existing = await redis_client.get(cache_key)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Duplicate request. Lead already processed "
                    f"with idempotency key: {idempotency_key}"
                ),
            )

        # Create lead record
        lead = Lead(
            source=body.source,
            raw_payload=body.data,
            status=LeadStatus.NEW,
        )
        db.add(lead)
        await db.flush()

        # Mark idempotency key as used
        await redis_client.setex(cache_key, settings.idempotency_key_ttl_seconds, str(lead.id))

        # Dispatch async processing
        process_lead_pipeline.delay(str(lead.id))

        logger.info("lead_received", lead_id=str(
            lead.id), source=body.source.value)
        return lead
    finally:
        await redis_client.aclose()
