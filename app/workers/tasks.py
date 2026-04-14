import asyncio
import csv
import io
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.logging import get_logger
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.lead_event import LeadEvent
from app.models.workflow_run import WorkflowRun, WorkflowStepStatus
from app.services.crm import sync_lead_to_crm
from app.services.dedup import check_and_register_dedup
from app.services.extraction import extract_lead_data
from app.services.notification import send_slack_notification
from app.services.scoring import compute_lead_score
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


def _get_sync_session() -> Session:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(settings.database_url_sync)
    return sessionmaker(bind=engine)()


def _get_async_session():
    from app.database import async_session_factory

    return async_session_factory()


def _log_step(db: Session, lead_id: uuid.UUID, step: str, status: WorkflowStepStatus,
              input_payload: dict | None = None, output_payload: dict | None = None,
              error_message: str | None = None, attempt: int = 1):
    run = WorkflowRun(
        lead_id=lead_id,
        step_name=step,
        status=status,
        input_payload=input_payload,
        output_payload=output_payload,
        error_message=error_message,
        attempt_number=attempt,
    )
    db.add(run)
    db.commit()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=4)
def process_lead_pipeline(self, lead_id: str, start_from_step: str = "extract"):
    """Main pipeline: extract → validate/dedupe → score → branch → crm sync → notify."""
    lid = uuid.UUID(lead_id)

    async def _run():
        async with _get_async_session() as db:
            result = await db.execute(select(Lead).where(Lead.id == lid))
            lead = result.scalar_one_or_none()
            if lead is None:
                logger.error("pipeline_lead_not_found", lead_id=lead_id)
                return

            lead.status = LeadStatus.PROCESSING
            await db.commit()

            steps = ["extract", "validate", "score",
                     "branch", "crm_sync", "notify"]
            start_idx = steps.index(
                start_from_step) if start_from_step in steps else 0

            try:
                for step in steps[start_idx:]:
                    if step == "extract":
                        await _step_extract(db, lead)
                    elif step == "validate":
                        await _step_validate(db, lead)
                    elif step == "score":
                        await _step_score(db, lead)
                    elif step == "branch":
                        should_continue = await _step_branch(db, lead)
                        if not should_continue:
                            return  # Waiting for human approval
                    elif step == "crm_sync":
                        await _step_crm_sync(db, lead)
                    elif step == "notify":
                        await _step_notify(db, lead)
            except Exception as e:
                lead.status = LeadStatus.FAILED
                event = LeadEvent(
                    lead_id=lead.id,
                    event_type="pipeline_failed",
                    payload={"error": str(e)},
                )
                db.add(event)
                await db.commit()
                logger.error("pipeline_failed", lead_id=lead_id, error=str(e))
                raise self.retry(exc=e)

    asyncio.run(_run())


async def _step_extract(db, lead: Lead):
    _add_run(db, lead.id, "extract", WorkflowStepStatus.RUNNING)
    extracted = await extract_lead_data(lead.raw_payload)
    lead.name = extracted.name
    lead.email = extracted.email
    lead.company = extracted.company
    lead.phone = extracted.phone
    lead.title = extracted.title
    lead.intent = extracted.intent
    lead.confidence_score = extracted.confidence_score
    _add_run(db, lead.id, "extract", WorkflowStepStatus.SUCCEEDED,
             output_payload=extracted.model_dump(mode="json"))
    await db.commit()


async def _step_validate(db, lead: Lead):
    _add_run(db, lead.id, "validate", WorkflowStepStatus.RUNNING)
    is_dup, dup_of = await check_and_register_dedup(db, lead)
    output = {"is_duplicate": is_dup,
              "duplicate_of": str(dup_of) if dup_of else None}
    if is_dup:
        lead.status = LeadStatus.FAILED
        _add_run(db, lead.id, "validate", WorkflowStepStatus.FAILED,
                 output_payload=output, error_message=f"Duplicate of {dup_of}")
        event = LeadEvent(lead_id=lead.id, event_type="duplicate_detected",
                          payload={"duplicate_of": str(dup_of)})
        db.add(event)
        await db.commit()
        raise Exception(f"Duplicate lead detected, duplicate of {dup_of}")
    _add_run(db, lead.id, "validate",
             WorkflowStepStatus.SUCCEEDED, output_payload=output)
    await db.commit()


async def _step_score(db, lead: Lead):
    _add_run(db, lead.id, "score", WorkflowStepStatus.RUNNING)
    lead.score = compute_lead_score(lead)
    _add_run(db, lead.id, "score", WorkflowStepStatus.SUCCEEDED,
             output_payload={"score": lead.score})
    await db.commit()


async def _step_branch(db, lead: Lead) -> bool:
    """Returns True if pipeline should continue to CRM sync, False if needs human review."""
    _add_run(db, lead.id, "branch", WorkflowStepStatus.RUNNING)
    if lead.confidence_score >= settings.confidence_threshold:
        lead.status = LeadStatus.APPROVED
        _add_run(db, lead.id, "branch", WorkflowStepStatus.SUCCEEDED,
                 output_payload={"decision": "auto_approve", "confidence": lead.confidence_score})
        event = LeadEvent(lead_id=lead.id, event_type="auto_approved",
                          payload={"confidence": lead.confidence_score})
        db.add(event)
        await db.commit()
        return True
    else:
        lead.status = LeadStatus.NEEDS_REVIEW
        _add_run(db, lead.id, "branch", WorkflowStepStatus.SUCCEEDED,
                 output_payload={"decision": "needs_review", "confidence": lead.confidence_score})
        event = LeadEvent(lead_id=lead.id, event_type="needs_review",
                          payload={"confidence": lead.confidence_score})
        db.add(event)
        await db.commit()
        await send_slack_notification(lead, event="needs_review")
        return False


async def _step_crm_sync(db, lead: Lead):
    _add_run(db, lead.id, "crm_sync", WorkflowStepStatus.RUNNING)
    result = await sync_lead_to_crm(lead)
    if result.get("success"):
        lead.crm_id = result["crm_id"]
        lead.status = LeadStatus.SYNCED
        _add_run(db, lead.id, "crm_sync", WorkflowStepStatus.SUCCEEDED,
                 output_payload=result)
        event = LeadEvent(
            lead_id=lead.id, event_type="crm_synced", payload=result)
        db.add(event)
        await db.commit()
    else:
        _add_run(db, lead.id, "crm_sync", WorkflowStepStatus.FAILED,
                 output_payload=result, error_message=result.get("error"))
        await db.commit()
        raise Exception(f"CRM sync failed: {result.get('error')}")


async def _step_notify(db, lead: Lead):
    _add_run(db, lead.id, "notify", WorkflowStepStatus.RUNNING)
    sent = await send_slack_notification(lead, event="new_lead")
    _add_run(db, lead.id, "notify", WorkflowStepStatus.SUCCEEDED,
             output_payload={"slack_sent": sent})
    event = LeadEvent(
        lead_id=lead.id, event_type="notification_sent", payload={"slack": sent})
    db.add(event)
    await db.commit()


def _add_run(db, lead_id: uuid.UUID, step: str, status: WorkflowStepStatus,
             output_payload: dict | None = None, error_message: str | None = None):
    run = WorkflowRun(
        lead_id=lead_id, step_name=step, status=status,
        output_payload=output_payload, error_message=error_message,
    )
    db.add(run)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=4)
def process_csv_upload(self, csv_content: str, user_id: str):
    """Parse CSV and create leads, then dispatch each through the pipeline."""

    async def _run():
        async with _get_async_session() as db:
            reader = csv.DictReader(io.StringIO(csv_content))
            count = 0
            for row in reader:
                lead = Lead(
                    source=LeadSource.CSV_UPLOAD,
                    raw_payload=dict(row),
                    name=row.get("name"),
                    email=row.get("email"),
                    company=row.get("company"),
                    phone=row.get("phone"),
                    title=row.get("title") or row.get("job_title"),
                    status=LeadStatus.NEW,
                )
                db.add(lead)
                await db.flush()
                process_lead_pipeline.delay(str(lead.id))
                count += 1
            await db.commit()
            logger.info("csv_upload_processed",
                        user_id=user_id, lead_count=count)

    asyncio.run(_run())


@celery_app.task(bind=True, max_retries=3, default_retry_delay=4)
def retry_workflow_step(self, run_id: str):
    """Retry a specific failed workflow step."""

    async def _run():
        async with _get_async_session() as db:
            result = await db.execute(
                select(WorkflowRun).where(WorkflowRun.id == uuid.UUID(run_id))
            )
            run = result.scalar_one_or_none()
            if run is None:
                logger.error("retry_run_not_found", run_id=run_id)
                return

            lead_result = await db.execute(select(Lead).where(Lead.id == run.lead_id))
            lead = lead_result.scalar_one_or_none()
            if lead is None:
                logger.error("retry_lead_not_found", lead_id=str(run.lead_id))
                return

            step_map = {
                "extract": _step_extract,
                "validate": _step_validate,
                "score": _step_score,
                "crm_sync": _step_crm_sync,
                "notify": _step_notify,
            }

            step_fn = step_map.get(run.step_name)
            if step_fn is None:
                logger.error("retry_unknown_step", step=run.step_name)
                return

            try:
                await step_fn(db, lead)
            except Exception as e:
                logger.error("retry_step_failed", run_id=run_id, error=str(e))
                raise self.retry(exc=e)

    asyncio.run(_run())
