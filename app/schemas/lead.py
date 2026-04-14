import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.lead import LeadIntent, LeadSource, LeadStatus


class WebhookLeadPayload(BaseModel):
    source: LeadSource = LeadSource.WEB_FORM
    data: dict = Field(..., description="Raw lead data from the source system")


class LeadCreate(BaseModel):
    source: LeadSource
    name: str | None = None
    email: str | None = None
    company: str | None = None
    phone: str | None = None
    title: str | None = None
    raw_payload: dict = Field(default_factory=dict)


class LeadUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    company: str | None = None
    phone: str | None = None
    title: str | None = None
    intent: LeadIntent | None = None
    score: int | None = Field(None, ge=0, le=100)
    owner_id: uuid.UUID | None = None


class LeadResponse(BaseModel):
    id: uuid.UUID
    source: LeadSource
    raw_payload: dict
    name: str | None
    email: str | None
    company: str | None
    phone: str | None
    title: str | None
    intent: LeadIntent
    score: int
    confidence_score: float
    status: LeadStatus
    owner_id: uuid.UUID | None
    crm_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeadListResponse(BaseModel):
    items: list[LeadResponse]
    total: int
    page: int
    page_size: int


class LeadEventResponse(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    event_type: str
    payload: dict
    created_at: datetime

    model_config = {"from_attributes": True}
