import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LeadSource(enum.StrEnum):
    WEB_FORM = "web_form"
    EMAIL = "email"
    CSV_UPLOAD = "csv_upload"


class LeadIntent(enum.StrEnum):
    DEMO_REQUEST = "demo_request"
    PRICING_INQUIRY = "pricing_inquiry"
    SUPPORT = "support"
    PARTNERSHIP = "partnership"
    GENERAL_INQUIRY = "general_inquiry"
    UNKNOWN = "unknown"


class LeadStatus(enum.StrEnum):
    NEW = "new"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    SYNCED = "synced"
    FAILED = "failed"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(
        Enum(LeadSource, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    raw_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict)
    name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(320))
    company: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(
        Enum(LeadIntent, values_callable=lambda x: [e.value for e in x]),
        default=LeadIntent.UNKNOWN,
    )
    score: Mapped[int] = mapped_column(Integer, default=0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(
        Enum(LeadStatus, values_callable=lambda x: [e.value for e in x]),
        default=LeadStatus.NEW,
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True)
    crm_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    events = relationship("LeadEvent", back_populates="lead", lazy="selectin")
    workflow_runs = relationship(
        "WorkflowRun", back_populates="lead", lazy="selectin")
    dedupe_keys = relationship(
        "DedupeKey", back_populates="lead", lazy="selectin")

    __table_args__ = (
        Index("ix_leads_email", "email"),
        Index("ix_leads_crm_id", "crm_id"),
        Index("ix_leads_status", "status"),
        Index("ix_leads_created_at", "created_at"),
    )
