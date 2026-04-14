from app.logging import get_logger
from app.models.lead import Lead

logger = get_logger(__name__)


async def enrich_lead(lead: Lead) -> dict:
    """Enrich lead with company data. Stubbed for MVP — returns empty enrichment.

    Future: integrate Clearbit/Apollo API for company domain lookup.
    """
    enrichment_data: dict = {}

    # Derive company domain from email if available
    if lead.email and "@" in lead.email:
        domain = lead.email.split("@")[-1].lower()
        free_domains = {"gmail.com", "yahoo.com",
                        "hotmail.com", "outlook.com", "aol.com"}
        if domain not in free_domains:
            enrichment_data["company_domain"] = domain

    if enrichment_data:
        logger.info("enrichment_complete", lead_id=str(
            lead.id), data=enrichment_data)
    else:
        logger.info("enrichment_skipped", lead_id=str(lead.id))

    return enrichment_data
