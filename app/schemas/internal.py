import uuid

from pydantic import BaseModel, Field

from app.models.lead import LeadIntent, LeadSource
from app.models.workflow_run import WorkflowStepStatus


# --- Normalize ---
class NormalizeRequest(BaseModel):
    source: LeadSource
    raw_data: dict


class NormalizeResponse(BaseModel):
    lead_id: uuid.UUID
    normalized: dict


# --- Extract ---
class ExtractRequest(BaseModel):
    lead_id: uuid.UUID


class ExtractResponse(BaseModel):
    lead_id: uuid.UUID
    name: str | None = None
    email: str | None = None
    company: str | None = None
    phone: str | None = None
    title: str | None = None
    intent: LeadIntent = LeadIntent.UNKNOWN
    confidence_score: float = Field(0.0, ge=0.0, le=1.0)


# --- Validate & Dedupe ---
class ValidateRequest(BaseModel):
    lead_id: uuid.UUID


class ValidateResponse(BaseModel):
    lead_id: uuid.UUID
    is_valid: bool
    is_duplicate: bool
    duplicate_of: uuid.UUID | None = None
    errors: list[str] = Field(default_factory=list)


# --- Enrich ---
class EnrichRequest(BaseModel):
    lead_id: uuid.UUID


class EnrichResponse(BaseModel):
    lead_id: uuid.UUID
    enriched: bool
    data: dict = Field(default_factory=dict)


# --- CRM Sync ---
class CrmSyncRequest(BaseModel):
    lead_id: uuid.UUID


class CrmSyncResponse(BaseModel):
    lead_id: uuid.UUID
    crm_id: str | None = None
    synced: bool
    error: str | None = None


# --- Log Step ---
class LogStepRequest(BaseModel):
    lead_id: uuid.UUID
    step_name: str
    status: WorkflowStepStatus
    input_payload: dict | None = None
    output_payload: dict | None = None
    error_message: str | None = None
    attempt_number: int = 1


class LogStepResponse(BaseModel):
    id: uuid.UUID
    recorded: bool = True
