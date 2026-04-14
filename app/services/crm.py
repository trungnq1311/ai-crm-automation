import httpx

from app.config import settings
from app.logging import get_logger
from app.models.lead import Lead

logger = get_logger(__name__)


async def sync_lead_to_crm(lead: Lead) -> dict:
    """Create or update a contact in HubSpot."""
    if not settings.hubspot_access_token:
        logger.warning("hubspot_token_missing",
                       msg="Skipping CRM sync — no token configured")
        return {"success": True, "crm_id": f"mock-{lead.id}", "mock": True}

    url = "https://api.hubapi.com/crm/v3/objects/contacts"
    headers = {
        "Authorization": f"Bearer {settings.hubspot_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "properties": {
            "email": lead.email or "",
            "firstname": (lead.name or "").split(" ")[0] if lead.name else "",
            "lastname": " ".join((lead.name or "").split(" ")[1:]) if lead.name else "",
            "company": lead.company or "",
            "phone": lead.phone or "",
            "jobtitle": lead.title or "",
        }
    }

    async with httpx.AsyncClient(timeout=settings.crm_timeout_seconds) as client:
        # Try to create
        try:
            resp = await client.post(url, json=payload, headers=headers)

            if resp.status_code == 409:
                # Contact already exists — try to find and update
                return await _update_existing_contact(client, headers, lead)

            if resp.status_code == 429:
                logger.warning("hubspot_rate_limited", lead_id=str(lead.id))
                return {"success": False, "error": "Rate limited by HubSpot"}

            resp.raise_for_status()
            crm_id = resp.json().get("id")
            logger.info("crm_sync_success", lead_id=str(
                lead.id), crm_id=crm_id)
            return {"success": True, "crm_id": crm_id}

        except httpx.HTTPStatusError as e:
            logger.error("crm_sync_failed", lead_id=str(
                lead.id), status=e.response.status_code)
            return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text}"}
        except httpx.TimeoutException:
            logger.error("crm_sync_timeout", lead_id=str(lead.id))
            return {"success": False, "error": "CRM sync timed out"}


async def _update_existing_contact(
    client: httpx.AsyncClient, headers: dict, lead: Lead
) -> dict:
    """Search for existing contact by email and update."""
    search_url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
    search_payload = {
        "filterGroups": [
            {
                "filters": [
                    {"propertyName": "email", "operator": "EQ", "value": lead.email}
                ]
            }
        ]
    }

    try:
        resp = await client.post(search_url, json=search_payload, headers=headers)
        resp.raise_for_status()
        results = resp.json().get("results", [])

        if not results:
            return {"success": False, "error": "Contact conflict but not found in search"}

        contact_id = results[0]["id"]
        update_url = f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}"
        update_payload = {
            "properties": {
                "company": lead.company or "",
                "phone": lead.phone or "",
                "jobtitle": lead.title or "",
            }
        }
        resp = await client.patch(update_url, json=update_payload, headers=headers)
        resp.raise_for_status()
        logger.info("crm_update_success", lead_id=str(
            lead.id), crm_id=contact_id)
        return {"success": True, "crm_id": contact_id}

    except Exception as e:
        logger.error("crm_update_failed", lead_id=str(lead.id), error=str(e))
        return {"success": False, "error": str(e)}
