import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.workflow_run import WorkflowStepStatus


class WorkflowRunResponse(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    step_name: str
    status: WorkflowStepStatus
    input_payload: dict | None
    output_payload: dict | None
    error_message: str | None
    attempt_number: int
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowRunListResponse(BaseModel):
    items: list[WorkflowRunResponse]
    total: int
    page: int
    page_size: int
