import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.lead import Lead, LeadIntent, LeadSource, LeadStatus
from app.models.lead_event import LeadEvent
from app.models.user import User
from app.schemas.lead import LeadEventResponse, LeadListResponse, LeadResponse, LeadUpdate
from app.workers.tasks import process_csv_upload, process_lead_pipeline

router = APIRouter()

MAX_CSV_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_csv(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV files are accepted",
        )

    content = await file.read()
    if len(content) > MAX_CSV_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File exceeds 10MB limit",
        )

    process_csv_upload.delay(content.decode("utf-8"), str(user.id))
    return {"message": "CSV upload accepted for processing", "filename": file.filename}


@router.get("", response_model=LeadListResponse)
async def list_leads(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: LeadStatus | None = Query(None, alias="status"),
    source: LeadSource | None = None,
    intent: LeadIntent | None = None,
):
    query = select(Lead)
    count_query = select(func.count(Lead.id))

    if status_filter:
        query = query.where(Lead.status == status_filter)
        count_query = count_query.where(Lead.status == status_filter)
    if source:
        query = query.where(Lead.source == source)
        count_query = count_query.where(Lead.source == source)
    if intent:
        query = query.where(Lead.intent == intent)
        count_query = count_query.where(Lead.intent == intent)

    total = (await db.execute(count_query)).scalar() or 0
    offset = (page - 1) * page_size
    result = await db.execute(
        query.order_by(Lead.created_at.desc()).offset(offset).limit(page_size)
    )
    leads = result.scalars().all()

    return LeadListResponse(items=leads, total=total, page=page, page_size=page_size)


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return lead


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: uuid.UUID,
    body: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(lead, field, value)
    await db.flush()
    return lead


@router.post("/{lead_id}/approve", response_model=LeadResponse)
async def approve_lead(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    if lead.status != LeadStatus.NEEDS_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lead status is '{lead.status.value}', expected 'needs_review'",
        )

    lead.status = LeadStatus.APPROVED
    event = LeadEvent(lead_id=lead.id, event_type="approved",
                      payload={"approved_by": str(user.id)})
    db.add(event)
    await db.flush()

    # Trigger CRM sync for approved lead
    process_lead_pipeline.delay(str(lead.id), start_from_step="crm_sync")

    return lead


@router.get("/{lead_id}/events", response_model=list[LeadEventResponse])
async def get_lead_events(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(LeadEvent).where(LeadEvent.lead_id ==
                                lead_id).order_by(LeadEvent.created_at.asc())
    )
    return result.scalars().all()
