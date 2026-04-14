
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.database import get_db
from app.models.lead import Lead, LeadStatus
from app.models.workflow_run import WorkflowRun
from app.schemas.internal import (
    CrmSyncRequest,
    CrmSyncResponse,
    EnrichRequest,
    EnrichResponse,
    ExtractRequest,
    ExtractResponse,
    LogStepRequest,
    LogStepResponse,
    NormalizeRequest,
    NormalizeResponse,
    ValidateRequest,
    ValidateResponse,
)
from app.services.crm import sync_lead_to_crm
from app.services.dedup import check_and_register_dedup
from app.services.enrichment import enrich_lead
from app.services.extraction import extract_lead_data

router = APIRouter()


@router.post("/normalize", response_model=NormalizeResponse)
async def normalize(
    body: NormalizeRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    lead = Lead(source=body.source, raw_payload=body.raw_data,
                status=LeadStatus.PROCESSING)
    db.add(lead)
    await db.flush()
    return NormalizeResponse(lead_id=lead.id, normalized=body.raw_data)


@router.post("/extract", response_model=ExtractResponse)
async def extract(
    body: ExtractRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    result = await db.execute(select(Lead).where(Lead.id == body.lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    extracted = await extract_lead_data(lead.raw_payload)

    lead.name = extracted.name
    lead.email = extracted.email
    lead.company = extracted.company
    lead.phone = extracted.phone
    lead.title = extracted.title
    lead.intent = extracted.intent
    lead.confidence_score = extracted.confidence_score
    await db.flush()

    return ExtractResponse(
        lead_id=lead.id,
        name=extracted.name,
        email=extracted.email,
        company=extracted.company,
        phone=extracted.phone,
        title=extracted.title,
        intent=extracted.intent,
        confidence_score=extracted.confidence_score,
    )


@router.post("/validate", response_model=ValidateResponse)
async def validate(
    body: ValidateRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    result = await db.execute(select(Lead).where(Lead.id == body.lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    errors = []
    if not lead.email and not lead.phone:
        errors.append("At least one of email or phone is required")

    is_duplicate, duplicate_of = await check_and_register_dedup(db, lead)

    return ValidateResponse(
        lead_id=lead.id,
        is_valid=len(errors) == 0,
        is_duplicate=is_duplicate,
        duplicate_of=duplicate_of,
        errors=errors,
    )


@router.post("/enrich", response_model=EnrichResponse)
async def enrich(
    body: EnrichRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    result = await db.execute(select(Lead).where(Lead.id == body.lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    enrichment_data = await enrich_lead(lead)
    return EnrichResponse(lead_id=lead.id, enriched=bool(enrichment_data), data=enrichment_data)


@router.post("/crm-sync", response_model=CrmSyncResponse)
async def crm_sync(
    body: CrmSyncRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    result = await db.execute(select(Lead).where(Lead.id == body.lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    crm_result = await sync_lead_to_crm(lead)
    if crm_result.get("success"):
        lead.crm_id = crm_result["crm_id"]
        lead.status = LeadStatus.SYNCED
        await db.flush()
        return CrmSyncResponse(lead_id=lead.id, crm_id=crm_result["crm_id"], synced=True)
    else:
        return CrmSyncResponse(lead_id=lead.id, synced=False, error=crm_result.get("error"))


@router.post("/log", response_model=LogStepResponse)
async def log_step(
    body: LogStepRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
):
    run = WorkflowRun(
        lead_id=body.lead_id,
        step_name=body.step_name,
        status=body.status,
        input_payload=body.input_payload,
        output_payload=body.output_payload,
        error_message=body.error_message,
        attempt_number=body.attempt_number,
    )
    db.add(run)
    await db.flush()
    return LogStepResponse(id=run.id, recorded=True)
