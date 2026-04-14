import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.workflow_run import WorkflowRun, WorkflowStepStatus
from app.schemas.workflow import WorkflowRunListResponse, WorkflowRunResponse
from app.workers.tasks import retry_workflow_step

router = APIRouter()


@router.get("", response_model=WorkflowRunListResponse)
async def list_workflow_runs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    lead_id: uuid.UUID | None = None,
    status_filter: WorkflowStepStatus | None = Query(None, alias="status"),
):
    query = select(WorkflowRun)
    count_query = select(func.count(WorkflowRun.id))

    if lead_id:
        query = query.where(WorkflowRun.lead_id == lead_id)
        count_query = count_query.where(WorkflowRun.lead_id == lead_id)
    if status_filter:
        query = query.where(WorkflowRun.status == status_filter)
        count_query = count_query.where(WorkflowRun.status == status_filter)

    total = (await db.execute(count_query)).scalar() or 0
    offset = (page - 1) * page_size
    result = await db.execute(
        query.order_by(WorkflowRun.created_at.desc()
                       ).offset(offset).limit(page_size)
    )
    runs = result.scalars().all()
    return WorkflowRunListResponse(items=runs, total=total, page=page, page_size=page_size)


@router.get("/{run_id}", response_model=WorkflowRunResponse)
async def get_workflow_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Workflow run not found")
    return run


@router.post("/{run_id}/retry", response_model=WorkflowRunResponse)
async def retry_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Workflow run not found")
    if run.status != WorkflowStepStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed steps can be retried",
        )

    run.status = WorkflowStepStatus.PENDING
    run.attempt_number += 1
    run.error_message = None
    await db.flush()

    retry_workflow_step.delay(str(run.id))
    return run
