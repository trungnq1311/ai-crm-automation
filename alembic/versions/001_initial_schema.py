"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-04-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum types
lead_source = postgresql.ENUM(
    "web_form", "email", "csv_upload", name="leadsource", create_type=False)
lead_intent = postgresql.ENUM(
    "demo_request", "pricing_inquiry", "support", "partnership", "general_inquiry", "unknown",
    name="leadintent", create_type=False,
)
lead_status = postgresql.ENUM(
    "new", "processing", "needs_review", "approved", "synced", "failed",
    name="leadstatus", create_type=False,
)
workflow_step_status = postgresql.ENUM(
    "pending", "running", "succeeded", "failed", "skipped",
    name="workflowstepstatus", create_type=False,
)
dedupe_key_type = postgresql.ENUM(
    "email_exact", "phone_normalized", "company_name_fuzzy", "composite_hash",
    name="dedupekeytype", create_type=False,
)
user_role = postgresql.ENUM(
    "admin", "sales_rep", "viewer", name="userrole", create_type=False)


def upgrade() -> None:
    # Create enum types
    lead_source.create(op.get_bind(), checkfirst=True)
    lead_intent.create(op.get_bind(), checkfirst=True)
    lead_status.create(op.get_bind(), checkfirst=True)
    workflow_step_status.create(op.get_bind(), checkfirst=True)
    dedupe_key_type.create(op.get_bind(), checkfirst=True)
    user_role.create(op.get_bind(), checkfirst=True)

    # Users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.String(320), unique=True, nullable=False),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("role", user_role, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )

    # Leads
    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", lead_source, nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(),
                  nullable=False, server_default="{}"),
        sa.Column("name", sa.Text()),
        sa.Column("email", sa.String(320)),
        sa.Column("company", sa.Text()),
        sa.Column("phone", sa.String(50)),
        sa.Column("title", sa.Text()),
        sa.Column("intent", lead_intent, server_default="unknown"),
        sa.Column("score", sa.Integer(), server_default="0"),
        sa.Column("confidence_score", sa.Float(), server_default="0.0"),
        sa.Column("status", lead_status, server_default="new"),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("crm_id", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index("ix_leads_email", "leads", ["email"])
    op.create_index("ix_leads_crm_id", "leads", ["crm_id"])
    op.create_index("ix_leads_status", "leads", ["status"])
    op.create_index("ix_leads_created_at", "leads", ["created_at"])

    # Lead events
    op.create_table(
        "lead_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(
            "leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index("ix_lead_events_lead_id", "lead_events", ["lead_id"])

    # Workflow runs
    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(
            "leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_name", sa.Text(), nullable=False),
        sa.Column("status", workflow_step_status, server_default="pending"),
        sa.Column("input_payload", postgresql.JSONB()),
        sa.Column("output_payload", postgresql.JSONB()),
        sa.Column("error_message", sa.Text()),
        sa.Column("attempt_number", sa.Integer(), server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index("ix_workflow_runs_lead_id", "workflow_runs", ["lead_id"])

    # Dedupe keys
    op.create_table(
        "dedupe_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(
            "leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_type", dedupe_key_type, nullable=False),
        sa.Column("key_value", sa.String(512), nullable=False),
    )
    op.create_index("ix_dedupe_keys_key_value", "dedupe_keys", ["key_value"])
    op.create_unique_constraint("uq_dedupe_key_type_value", "dedupe_keys", [
                                "key_type", "key_value"])


def downgrade() -> None:
    op.drop_table("dedupe_keys")
    op.drop_table("workflow_runs")
    op.drop_table("lead_events")
    op.drop_table("leads")
    op.drop_table("users")

    enum_names = [
        "userrole", "dedupekeytype", "workflowstepstatus",
        "leadstatus", "leadintent", "leadsource",
    ]
    for name in enum_names:
        op.execute(f"DROP TYPE IF EXISTS {name}")
