import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead, LeadSource, LeadStatus
from app.services.dedup import (
    _composite_hash,
    _fuzzy_company_key,
    _normalize_email,
    _normalize_phone,
    check_and_register_dedup,
)


def test_normalize_email():
    assert _normalize_email("  John@Example.COM  ") == "john@example.com"


def test_normalize_phone_valid():
    result = _normalize_phone("+1 (212) 555-1234")
    assert result == "+12125551234"


def test_normalize_phone_invalid():
    assert _normalize_phone("not-a-phone") is None


def test_fuzzy_company_key():
    key1 = _fuzzy_company_key("Acme Corp", "John Doe")
    key2 = _fuzzy_company_key("  acme corp  ", "  john doe  ")
    assert key1 == key2


def test_composite_hash_deterministic():
    h1 = _composite_hash("a@b.com", "+1234", "Acme")
    h2 = _composite_hash("a@b.com", "+1234", "Acme")
    assert h1 == h2


def test_composite_hash_differs():
    h1 = _composite_hash("a@b.com", "+1234", "Acme")
    h2 = _composite_hash("x@y.com", "+1234", "Acme")
    assert h1 != h2


@pytest.mark.asyncio
async def test_dedup_registers_keys(db_session: AsyncSession):
    lead = Lead(
        source=LeadSource.WEB_FORM,
        raw_payload={},
        name="John Doe",
        email="john@acme.com",
        company="Acme",
        phone="(555) 123-4567",
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    await db_session.flush()

    is_dup, dup_of = await check_and_register_dedup(db_session, lead)
    assert is_dup is False
    assert dup_of is None

    # Verify keys were registered
    from sqlalchemy import select

    from app.models.dedupe_key import DedupeKey

    result = await db_session.execute(select(DedupeKey).where(DedupeKey.lead_id == lead.id))
    keys = result.scalars().all()
    # email, phone, composite (+ company_name if both present)
    assert len(keys) >= 3


@pytest.mark.asyncio
async def test_dedup_detects_duplicate(db_session: AsyncSession):
    lead1 = Lead(
        source=LeadSource.WEB_FORM,
        raw_payload={},
        name="John Doe",
        email="john@acme.com",
        status=LeadStatus.SYNCED,
    )
    db_session.add(lead1)
    await db_session.flush()

    # Register keys for lead1
    is_dup1, _ = await check_and_register_dedup(db_session, lead1)
    assert is_dup1 is False

    # Create lead2 with same email
    lead2 = Lead(
        source=LeadSource.EMAIL,
        raw_payload={},
        name="John Doe",
        email="john@acme.com",
        status=LeadStatus.NEW,
    )
    db_session.add(lead2)
    await db_session.flush()

    is_dup2, dup_of = await check_and_register_dedup(db_session, lead2)
    assert is_dup2 is True
    assert dup_of == lead1.id
