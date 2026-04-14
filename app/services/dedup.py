import hashlib
import uuid

import phonenumbers
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.dedupe_key import DedupeKey, DedupeKeyType
from app.models.lead import Lead

logger = get_logger(__name__)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_phone(phone: str) -> str | None:
    try:
        parsed = phonenumbers.parse(phone, "US")
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    return None


def _fuzzy_company_key(company: str, name: str) -> str:
    normalized = f"{company.strip().lower()}|{name.strip().lower()}"
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def _composite_hash(email: str | None, phone: str | None, company: str | None) -> str:
    parts = [
        (email or "").strip().lower(),
        (phone or "").strip(),
        (company or "").strip().lower(),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


async def check_and_register_dedup(
    db: AsyncSession, lead: Lead
) -> tuple[bool, uuid.UUID | None]:
    """Check for duplicates across all strategies. Register keys if new."""
    keys_to_check: list[tuple[DedupeKeyType, str]] = []

    if lead.email:
        keys_to_check.append(
            (DedupeKeyType.EMAIL_EXACT, _normalize_email(lead.email)))

    if lead.phone:
        normalized_phone = _normalize_phone(lead.phone)
        if normalized_phone:
            keys_to_check.append(
                (DedupeKeyType.PHONE_NORMALIZED, normalized_phone))

    if lead.company and lead.name:
        keys_to_check.append(
            (DedupeKeyType.COMPANY_NAME_FUZZY,
             _fuzzy_company_key(lead.company, lead.name))
        )

    composite = _composite_hash(lead.email, lead.phone, lead.company)
    keys_to_check.append((DedupeKeyType.COMPOSITE_HASH, composite))

    # Check existing keys
    for key_type, key_value in keys_to_check:
        result = await db.execute(
            select(DedupeKey).where(
                DedupeKey.key_type == key_type,
                DedupeKey.key_value == key_value,
                DedupeKey.lead_id != lead.id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            logger.info(
                "duplicate_found",
                lead_id=str(lead.id),
                duplicate_of=str(existing.lead_id),
                key_type=key_type.value,
            )
            return True, existing.lead_id

    # No duplicate — register all keys for this lead
    for key_type, key_value in keys_to_check:
        db.add(DedupeKey(lead_id=lead.id, key_type=key_type, key_value=key_value))
    await db.flush()

    return False, None
