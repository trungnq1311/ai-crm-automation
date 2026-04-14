from pydantic import BaseModel


class MetricsResponse(BaseModel):
    total_processed: int
    total_approved: int
    total_failed: int
    total_synced: int
    total_needs_review: int
    approval_rate: float
    failure_rate: float
    sync_success_rate: float
    avg_latency_seconds: float | None
    leads_by_source: dict[str, int]
    leads_by_intent: dict[str, int]
