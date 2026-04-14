import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead, LeadSource, LeadStatus


async def _create_lead(db: AsyncSession, **kwargs) -> Lead:
    defaults = {
        "source": LeadSource.WEB_FORM,
        "raw_payload": {"name": "Test Lead"},
        "name": "Test Lead",
        "email": "test@company.com",
        "company": "TestCo",
        "status": LeadStatus.NEW,
    }
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.add(lead)
    await db.flush()
    return lead


@pytest.mark.asyncio
async def test_list_leads(client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
    await _create_lead(db_session)
    await _create_lead(db_session, email="other@company.com", name="Other Lead")

    resp = await client.get("/leads", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_lead(client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
    lead = await _create_lead(db_session)
    resp = await client.get(f"/leads/{lead.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "test@company.com"


@pytest.mark.asyncio
async def test_get_lead_not_found(client: AsyncClient, auth_headers: dict):
    resp = await client.get(f"/leads/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_lead(client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
    lead = await _create_lead(db_session)
    resp = await client.patch(
        f"/leads/{lead.id}",
        json={"name": "Updated Name", "company": "NewCo"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"
    assert resp.json()["company"] == "NewCo"


@pytest.mark.asyncio
async def test_approve_lead(client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
    from unittest.mock import patch as mock_patch

    lead = await _create_lead(db_session, status=LeadStatus.NEEDS_REVIEW)

    with mock_patch("app.api.leads.process_lead_pipeline") as mock_task:
        mock_task.delay.return_value = None
        resp = await client.post(f"/leads/{lead.id}/approve", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_approve_lead_wrong_status(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    lead = await _create_lead(db_session, status=LeadStatus.NEW)
    resp = await client.post(f"/leads/{lead.id}/approve", headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_leads_filter_by_status(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    await _create_lead(db_session, status=LeadStatus.NEW, email="a@test.com")
    await _create_lead(db_session, status=LeadStatus.SYNCED, email="b@test.com")

    resp = await client.get("/leads?status=synced", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "synced"


@pytest.mark.asyncio
async def test_requires_auth(client: AsyncClient):
    resp = await client.get("/leads")
    assert resp.status_code == 403
