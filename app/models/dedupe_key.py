import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DedupeKeyType(enum.StrEnum):
    EMAIL_EXACT = "email_exact"
    PHONE_NORMALIZED = "phone_normalized"
    COMPANY_NAME_FUZZY = "company_name_fuzzy"
    COMPOSITE_HASH = "composite_hash"


class DedupeKey(Base):
    __tablename__ = "dedupe_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    key_type: Mapped[str] = mapped_column(
        Enum(DedupeKeyType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    key_value: Mapped[str] = mapped_column(String(512), nullable=False)

    lead = relationship("Lead", back_populates="dedupe_keys")

    __table_args__ = (
        Index("ix_dedupe_keys_key_value", "key_value"),
        UniqueConstraint("key_type", "key_value",
                         name="uq_dedupe_key_type_value"),
    )
