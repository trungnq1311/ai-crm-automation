from fastapi import APIRouter, Depends
from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.lead import Lead, LeadStatus
from app.models.user import User
from app.schemas.metrics import MetricsResponse

router = APIRouter()


def _enum_val(v: object) -> str:
    return v.value if hasattr(v, "value") else str(v)


@router.get("", response_model=MetricsResponse)
async def get_metrics(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Status counts
    status_q = select(Lead.status, func.count(Lead.id)).group_by(Lead.status)
    result = await db.execute(status_q)
    status_counts = {
        _enum_val(row[0]): row[1] for row in result.all()
    }

    total_processed = sum(status_counts.values())
    total_approved = (
        status_counts.get("approved", 0) + status_counts.get("synced", 0)
    )
    total_failed = status_counts.get("failed", 0)
    total_synced = status_counts.get("synced", 0)
    total_needs_review = status_counts.get("needs_review", 0)

    approval_rate = total_approved / total_processed if total_processed else 0.0
    failure_rate = total_failed / total_processed if total_processed else 0.0
    sync_rate = total_synced / total_approved if total_approved else 0.0

    # Avg latency (time from creation to sync)
    latency_q = select(
        func.avg(
            extract("epoch", Lead.updated_at)
            - extract("epoch", Lead.created_at)
        )
    ).where(Lead.status == LeadStatus.SYNCED)
    avg_latency = (await db.execute(latency_q)).scalar()

    # Leads by source
    source_q = select(Lead.source, func.count(Lead.id)).group_by(Lead.source)
    source_result = await db.execute(source_q)
    leads_by_source = {
        _enum_val(row[0]): row[1] for row in source_result.all()
    }

    # Leads by intent
    intent_q = select(Lead.intent, func.count(Lead.id)).group_by(Lead.intent)
    intent_result = await db.execute(intent_q)
    leads_by_intent = {
        _enum_val(row[0]): row[1] for row in intent_result.all()
    }

    return MetricsResponse(
        total_processed=total_processed,
        total_approved=total_approved,
        total_failed=total_failed,
        total_synced=total_synced,
        total_needs_review=total_needs_review,
        approval_rate=round(approval_rate, 4),
        failure_rate=round(failure_rate, 4),
        sync_success_rate=round(sync_rate, 4),
        avg_latency_seconds=round(avg_latency, 2) if avg_latency else None,
        leads_by_source=leads_by_source,
        leads_by_intent=leads_by_intent,
    )
