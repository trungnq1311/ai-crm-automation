from app.logging import get_logger
from app.models.lead import Lead, LeadIntent

logger = get_logger(__name__)

# Scoring weights
INTENT_SCORES: dict[LeadIntent, int] = {
    LeadIntent.DEMO_REQUEST: 40,
    LeadIntent.PRICING_INQUIRY: 35,
    LeadIntent.PARTNERSHIP: 30,
    LeadIntent.GENERAL_INQUIRY: 15,
    LeadIntent.SUPPORT: 10,
    LeadIntent.UNKNOWN: 5,
}

SENIORITY_KEYWORDS = {
    "c-level": ["ceo", "cto", "cfo", "coo", "cio", "chief"],
    "vp": ["vp", "vice president"],
    "director": ["director", "head of"],
    "manager": ["manager", "lead", "senior"],
}

SENIORITY_SCORES = {
    "c-level": 30,
    "vp": 25,
    "director": 20,
    "manager": 15,
}


def compute_lead_score(lead: Lead) -> int:
    score = 0

    # Intent score
    intent = LeadIntent(lead.intent) if isinstance(
        lead.intent, str) else lead.intent
    score += INTENT_SCORES.get(intent, 5)

    # Title seniority score
    if lead.title:
        title_lower = lead.title.lower()
        for level, keywords in SENIORITY_KEYWORDS.items():
            if any(kw in title_lower for kw in keywords):
                score += SENIORITY_SCORES[level]
                break

    # Company presence bonus
    if lead.company:
        score += 10

    # Email domain bonus (non-free email)
    if lead.email:
        free_domains = {"gmail.com", "yahoo.com",
                        "hotmail.com", "outlook.com", "aol.com"}
        domain = lead.email.split("@")[-1].lower() if "@" in lead.email else ""
        if domain and domain not in free_domains:
            score += 15

    # Phone presence bonus
    if lead.phone:
        score += 5

    return min(score, 100)
