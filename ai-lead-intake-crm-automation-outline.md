AI Lead Intake & CRM Routing Automation

1. MVP Scope

- Ingest leads from web form, email webhook, or CSV upload.
  - Validate and sanitize all inputs at the ingestion boundary (malformed payloads, oversized CSVs, spam filtering).
  - Enforce idempotency keys on webhook endpoints to prevent duplicate processing from retries.
- Use LLM to extract structured lead data and classify intent.
  - Use structured output via prompt-based JSON extraction with Pydantic validation — never rely on raw prompt output.
  - LLM provider: OpenRouter (OpenAI-compatible API) with free models (e.g., `meta-llama/llama-3.1-8b-instruct:free`).
  - Produce a confidence score per extraction to drive auto-sync vs. human-review branching.
- Deduplicate and enrich records.
  - Dedup strategies: email exact match, phone normalization, company+name fuzzy match (composite hash).
  - Enrichment: company domain lookup via Clearbit/Apollo free tier (or skip enrichment in MVP and mark as future enhancement).
- Route to the right owner/segment based on intent classification and lead score.
- Sync to CRM and notify sales.
- Keep audit logs, retries, error queue, and dead letter queue for permanently failed items.

2. Architecture

- Frontend: simple admin dashboard (React or plain HTML+JS).
- API: FastAPI.
- Workflow engine: n8n (self-hosted) — handles trigger/routing/notification orchestration only.
  - All business logic (normalization, extraction, validation, dedup) lives in FastAPI, called via HTTP from n8n.
  - n8n is the visual orchestrator; FastAPI is the brain.
- AI layer: OpenRouter (OpenAI-compatible API, https://openrouter.ai/api/v1) with free models only.
  - Default model: `meta-llama/llama-3.1-8b-instruct:free`.
  - Prompt-based JSON extraction with manual parsing and Pydantic validation (free models don't support function calling reliably).
- Data store: Postgres.
- Cache/broker: Redis (serves as both Celery broker and cache for dedup lookups / company enrichment).
- File store: S3-compatible storage (MinIO for local dev).
- Queue/worker: Celery with Redis broker — used for heavy async work only (LLM calls, CSV parsing, CRM sync). n8n handles lightweight orchestration.
- CRM: HubSpot free tier (well-documented API, generous free plan, no heavyweight sandbox setup).
- Notifications: Slack (primary) + email (fallback).
- Auth: API key auth on webhook endpoints, JWT/session auth on dashboard endpoints.

3. Data Model

leads:

- id (UUID, PK)
- source (enum: web_form, email, csv_upload)
- raw_payload (JSONB — original ingested data, stored for debugging/re-processing/audit)
- name (text)
- email (text, indexed)
- company (text)
- phone (text)
- title (text)
- intent (enum: demo_request, pricing_inquiry, support, partnership, general_inquiry, unknown)
- score (integer 0-100 — lead quality score, computed by rule engine based on intent + company size + title seniority)
- confidence_score (float 0.0-1.0 — LLM extraction confidence, drives auto-sync vs. human-review branching)
- status (enum: new → processing → needs_review → approved → synced → failed)
- owner_id (FK → users.id)
- crm_id (text, indexed — external CRM record ID)
- created_at (timestamptz)
- updated_at (timestamptz)

lead_events:

- id (UUID, PK)
- lead_id (FK → leads.id, indexed)
- event_type (text)
- payload (JSONB)
- created_at (timestamptz)

workflow_runs:

- id (UUID, PK)
- lead_id (FK → leads.id, indexed)
- step_name (text)
- status (enum: pending, running, succeeded, failed, skipped)
- input_payload (JSONB)
- output_payload (JSONB)
- error_message (text)
- attempt_number (integer, default 1)
- created_at (timestamptz)

dedupe_keys:

- id (UUID, PK)
- lead_id (FK → leads.id)
- key_type (enum: email_exact, phone_normalized, company_name_fuzzy, composite_hash)
- key_value (text, indexed)
- UNIQUE constraint on (key_type, key_value)

users:

- id (UUID, PK)
- name (text)
- email (text)
- role (enum: admin, sales_rep, viewer)

Indexes:

- leads.email
- leads.crm_id
- leads.status
- leads.created_at
- lead_events.lead_id
- workflow_runs.lead_id
- dedupe_keys.key_value
- dedupe_keys(key_type, key_value) UNIQUE

4. API Endpoints

Webhook & Ingestion:

- POST /webhooks/lead — receive lead from external source (API key auth, idempotency key in header)
- POST /leads/upload — CSV file upload (JWT auth, max 10MB, async processing via Celery)

Lead Management:

- GET /leads — list leads with filtering (status, source, intent, date range) and pagination
- GET /leads/{id} — lead detail including extracted fields, confidence, and raw payload
- PATCH /leads/{id} — manually correct extracted fields the LLM got wrong
- GET /leads/{id}/events — audit trail for a specific lead
- POST /leads/{id}/approve — approve a lead in needs_review status for CRM sync

Workflow Operations:

- GET /workflow-runs — list workflow runs with filtering by lead_id, status
- GET /workflow-runs/{id} — detail of a specific run
- POST /workflow-runs/{id}/retry — retry a specific failed step (not the full pipeline)

Observability:

- GET /metrics — returns: total processed, approval rate, failure rate, avg latency, leads by source, leads by intent, sync success rate

Auth:

- Webhook endpoints: API key in X-API-Key header
- All other endpoints: JWT bearer token (issued via login or OAuth)

5. n8n Workflow

Pipeline steps (n8n orchestrates, FastAPI executes):

1. Trigger: n8n webhook node receives inbound lead (or email parser trigger).
2. Normalize: n8n calls POST /internal/normalize on FastAPI — normalizes payload to canonical schema.
3. Extract: n8n calls POST /internal/extract on FastAPI — LLM extraction via OpenRouter (prompt-based JSON output, manually parsed and validated with Pydantic).
   - Returns structured fields + confidence_score.
   - Strategy: prompt instructs the LLM to return JSON; response is parsed with markdown fence stripping and JSON deserialization, validated by Pydantic on return.
   - Timeout: 30s per LLM call, fail after 2 retries with exponential backoff.
4. Validate & Dedupe: n8n calls POST /internal/validate on FastAPI — schema validation + dedup check against dedupe_keys table.
5. Enrichment: n8n calls POST /internal/enrich on FastAPI — company lookup (optional in MVP).
6. Branch: n8n IF node on confidence_score.
   - confidence >= 0.85 → auto-sync path.
   - confidence < 0.85 → set status to needs_review, wait for human approval via dashboard.
7. CRM Sync: n8n calls POST /internal/crm-sync on FastAPI — creates/updates HubSpot contact.
   - Handles 429 rate limits with exponential backoff (max 3 retries).
8. Notify: n8n Slack node sends formatted message to sales channel.
9. Log: n8n calls POST /internal/log on FastAPI — persists workflow_run records for each step.

Error handling:

- Each step writes its status to workflow_runs (pending → running → succeeded/failed).
- Failed steps are retried up to 3 times with exponential backoff (1s, 4s, 16s).
- After max retries, lead moves to failed status and enters dead letter queue.
- Dead letter items surface in the dashboard for manual investigation.

6. Key Demo Features

- Inbox of incoming leads with status badges and source indicators.
- Lead detail page with extracted fields, confidence score, and before/after comparison (raw input vs. structured output).
- Approval toggle for uncertain leads (confidence < 0.85).
- Workflow timeline with each step status, duration, and error details.
- Retry button for failed workflow runs (per-step granularity).
- Dead letter queue view for permanently failed items.
- Metrics dashboard: total processed, approval rate, failure rate, avg latency, leads by source, leads by intent, sync success rate.

7. Portfolio Story

- Problem: leads were arriving through messy channels and sales reps were wasting time cleaning data.
- Solution: build an AI workflow that extracts, validates, routes, and syncs leads automatically.
- Impact: reduced manual entry, faster response time, fewer duplicates.
- Skills shown: Python, API/webhooks, n8n, LLM APIs (OpenRouter free tier), CRM integration, deployment, observability.

8. Delivery Plan

- Week 1: Postgres schema + migrations, FastAPI skeleton with auth, webhook ingestion endpoint, CSV upload with Celery async processing, basic input validation, Docker Compose for local dev (Postgres + Redis + MinIO).
- Week 2: LLM extraction service (OpenRouter + prompt-based JSON parsing + Pydantic validation), dedup logic with all strategies, confidence scoring, HubSpot CRM sync (expect extra effort — CRM APIs have idiosyncratic auth flows, rate limits, and field mapping), integration tests for extraction and dedup (mock LLM API).
- Week 3: n8n self-hosted setup, full pipeline workflow wired to FastAPI internal endpoints, Slack notifications, workflow_runs logging, error handling + retry logic, dead letter queue.
- Week 4: Admin dashboard (lead inbox, detail with before/after, approval flow, workflow timeline, metrics), end-to-end testing, deploy (Docker Compose or Railway/Render), write case study.

Testing (runs continuously, not a single-week task):

- Unit tests: dedup logic, payload normalization, score computation.
- Integration tests: webhook ingestion → DB, LLM extraction (mocked API) → schema validation, CRM sync (mocked HubSpot API).
- End-to-end test: submit lead via webhook → verify it appears in dashboard with correct status.
- Use pytest + httpx (AsyncClient) for FastAPI testing.

9. Reliability & Operational Concerns

- Idempotency: webhook endpoint requires X-Idempotency-Key header; store processed keys in Redis with 24h TTL.
- Rate limiting: apply per-IP rate limiting on public webhook endpoint (e.g., 60 req/min via slowapi).
- Retry policy: all external calls (LLM, CRM, enrichment) use exponential backoff with jitter, max 3 attempts.
- Dead letter queue: failed items after max retries are persisted in a separate DB status, surfaced in dashboard, and alertable via Slack.
- Timeouts: LLM calls 30s, CRM calls 15s, enrichment calls 10s.
- Secrets management: all API keys (OpenRouter, HubSpot, Slack) stored in environment variables, never in code or DB. Use .env for local dev, platform secrets for production.
- Logging: structured JSON logs (structlog) with correlation IDs per lead for traceability across services.
