
from app.models.lead import Lead, LeadIntent, LeadSource, LeadStatus
from app.services.scoring import compute_lead_score


def _make_lead(**kwargs) -> Lead:
    defaults = {
        "source": LeadSource.WEB_FORM,
        "raw_payload": {},
        "intent": LeadIntent.UNKNOWN,
        "status": LeadStatus.NEW,
    }
    defaults.update(kwargs)
    return Lead(**defaults)


def test_score_unknown_minimal():
    lead = _make_lead()
    score = compute_lead_score(lead)
    assert score == 5  # just intent score for unknown


def test_score_demo_request_with_company_email():
    lead = _make_lead(
        intent=LeadIntent.DEMO_REQUEST,
        email="alice@bigcorp.com",
        company="BigCorp",
    )
    score = compute_lead_score(lead)
    # 40 (intent) + 10 (company) + 15 (business email) = 65
    assert score == 65


def test_score_c_level():
    lead = _make_lead(
        intent=LeadIntent.PRICING_INQUIRY,
        title="CEO",
        email="boss@startup.io",
        company="Startup",
        phone="+1555000000",
    )
    score = compute_lead_score(lead)
    # 35 (intent) + 30 (c-level) + 10 (company) + 15 (biz email) + 5 (phone) = 95
    assert score == 95


def test_score_capped_at_100():
    lead = _make_lead(
        intent=LeadIntent.DEMO_REQUEST,
        title="Chief Technology Officer",
        email="cto@megacorp.com",
        company="MegaCorp",
        phone="+1555000000",
    )
    score = compute_lead_score(lead)
    assert score == 100  # 40+30+10+15+5 = 100


def test_score_free_email():
    lead = _make_lead(
        intent=LeadIntent.GENERAL_INQUIRY,
        email="someone@gmail.com",
    )
    score = compute_lead_score(lead)
    # 15 (intent) + 0 (free email, no bonus) = 15
    assert score == 15
