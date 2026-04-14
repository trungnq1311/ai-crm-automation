# AI Lead Intake & CRM Routing Automation

An AI-powered platform that ingests leads from multiple channels (web forms, email webhooks, CSV uploads), uses LLM to extract structured data and classify intent, deduplicates records, scores and routes leads, syncs to HubSpot CRM, and notifies sales via Slack.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Data Model](#data-model)
- [API Endpoints](#api-endpoints)
- [Lead Processing Pipeline](#lead-processing-pipeline)
- [Services](#services)
- [Admin Dashboard](#admin-dashboard)
- [n8n Integration](#n8n-integration)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Running Tests](#running-tests)
- [Docker Compose Stack](#docker-compose-stack)

---

## Architecture Overview

```
                    +------------------+
                    |   Web Form /     |
                    |   Email / CSV    |
                    +--------+---------+
                             |
                     POST /webhooks/lead
                     POST /leads/upload
                             |
                    +--------v---------+
                    |    FastAPI API    |<-----> JWT / API Key Auth
                    +--------+---------+
                             |
                   +---------v----------+
                   |   Celery Worker    |
                   |  (Redis broker)    |
                   +---------+----------+
                             |
            +-------+--------+--------+--------+--------+
            |       |        |        |        |        |
         Extract  Dedup    Score   Branch   CRM Sync  Notify
         (LLM)   (Postgres)        (>=0.85)  (HubSpot) (Slack)
            |       |        |        |        |        |
            v       v        v        v        v        v
                    +--------+---------+
                    |    PostgreSQL     |
                    +------------------+

                    +------------------+
                    |  Admin Dashboard |  (served at /)
                    +------------------+

                    +------------------+
                    |   n8n (visual    |  (optional orchestrator)
                    |   workflow)      |
                    +------------------+
```

**Design principles:**

- All business logic lives in FastAPI. n8n is an optional visual orchestrator calling internal endpoints.
- Celery handles heavy async work (LLM calls, CSV parsing, CRM sync).
- Confidence-based branching: >= 0.85 auto-syncs, < 0.85 goes to human review.

---

## Tech Stack

| Layer            | Technology                                                                                    |
| ---------------- | --------------------------------------------------------------------------------------------- |
| API              | FastAPI (async, Pydantic v2 schemas)                                                          |
| Database         | PostgreSQL 16 via SQLAlchemy 2.0 (async)                                                      |
| Migrations       | Alembic                                                                                       |
| Task Queue       | Celery with Redis broker                                                                      |
| Cache            | Redis (idempotency keys, dedup lookups)                                                       |
| LLM              | OpenRouter (OpenAI-compatible API) with free models (`meta-llama/llama-3.1-8b-instruct:free`) |
| CRM              | HubSpot (create/update contacts via REST API)                                                 |
| Notifications    | Slack (webhook)                                                                               |
| File Storage     | S3-compatible (MinIO for local dev)                                                           |
| Auth             | JWT bearer tokens (dashboard), API key (webhooks)                                             |
| Rate Limiting    | slowapi (per-IP on webhook endpoints)                                                         |
| Logging          | structlog (structured JSON with correlation IDs)                                              |
| Linting          | ruff                                                                                          |
| Testing          | pytest + pytest-asyncio + httpx                                                               |
| Containerization | Docker + Docker Compose                                                                       |
| Workflow         | n8n (self-hosted, optional)                                                                   |

---

## Project Structure

```
ai-crm-automation/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app factory, middleware, routers
│   ├── config.py                # Central settings (pydantic-settings)
│   ├── database.py              # Async SQLAlchemy engine + session factory
│   ├── logging.py               # structlog setup
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth.py              # POST /auth/login, POST /auth/register
│   │   ├── deps.py              # Auth dependencies (API key, JWT, idempotency)
│   │   ├── webhooks.py          # POST /webhooks/lead
│   │   ├── leads.py             # Leads CRUD + CSV upload + approve
│   │   ├── workflow_runs.py     # Workflow run list/detail/retry
│   │   ├── metrics.py           # GET /metrics (aggregated stats)
│   │   └── internal.py          # 6 internal endpoints for n8n
│   ├── models/
│   │   ├── __init__.py          # Re-exports all models
│   │   ├── lead.py              # Lead model + LeadSource/Intent/Status enums
│   │   ├── lead_event.py        # LeadEvent audit log model
│   │   ├── workflow_run.py      # WorkflowRun model + step status enum
│   │   ├── dedupe_key.py        # DedupeKey model + key type enum
│   │   └── user.py              # User model + role enum
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── auth.py              # Login/register/token schemas
│   │   ├── lead.py              # Lead request/response schemas
│   │   ├── workflow.py          # Workflow run schemas
│   │   ├── metrics.py           # Metrics response schema
│   │   └── internal.py          # Internal endpoint schemas
│   ├── services/
│   │   ├── __init__.py
│   │   ├── extraction.py        # LLM extraction via OpenRouter
│   │   ├── dedup.py             # 4-strategy deduplication
│   │   ├── scoring.py           # Rule-based lead scoring
│   │   ├── crm.py               # HubSpot CRM sync
│   │   ├── enrichment.py        # Company domain lookup (stub)
│   │   └── notification.py      # Slack notifications
│   └── workers/
│       ├── __init__.py
│       ├── celery_app.py        # Celery app configuration
│       └── tasks.py             # Pipeline tasks (process_lead, CSV, retry)
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py  # Full DDL for all 5 tables
├── frontend/
│   └── index.html               # Single-file admin dashboard (dark theme)
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures (db_session, client, auth)
│   ├── test_extraction.py       # 7 tests (parsing, fallback, mocked OpenRouter)
│   ├── test_scoring.py          # 5 tests (rule engine edge cases)
│   ├── test_dedup.py            # 8 tests (6 pure + 2 async DB)
│   ├── test_webhooks.py         # 4 tests (webhook endpoint)
│   └── test_leads.py            # 8 tests (leads CRUD)
├── docker-compose.yml           # Full local dev stack
├── Dockerfile                   # Python 3.11-slim
├── pyproject.toml               # Dependencies, ruff, pytest, mypy config
├── alembic.ini                  # Alembic configuration
├── .env.example                 # Environment variable template
├── .gitignore
└── ai-lead-intake-crm-automation-outline.md  # Original design outline
```

---

## Data Model

### leads

Core table storing all ingested leads.

| Column           | Type                 | Description                                                                               |
| ---------------- | -------------------- | ----------------------------------------------------------------------------------------- |
| id               | UUID (PK)            | Auto-generated                                                                            |
| source           | Enum                 | `web_form`, `email`, `csv_upload`                                                         |
| raw_payload      | JSONB                | Original ingested data (for debugging/reprocessing)                                       |
| name             | Text                 | Extracted full name                                                                       |
| email            | String(320), indexed | Contact email                                                                             |
| company          | Text                 | Company or organization                                                                   |
| phone            | String(50)           | Phone number                                                                              |
| title            | Text                 | Job title                                                                                 |
| intent           | Enum                 | `demo_request`, `pricing_inquiry`, `support`, `partnership`, `general_inquiry`, `unknown` |
| score            | Integer 0-100        | Lead quality score (rule engine)                                                          |
| confidence_score | Float 0.0-1.0        | LLM extraction confidence                                                                 |
| status           | Enum                 | `new` -> `processing` -> `needs_review` -> `approved` -> `synced` / `failed`              |
| owner_id         | UUID (FK)            | Assigned sales rep                                                                        |
| crm_id           | String, indexed      | External HubSpot contact ID                                                               |
| created_at       | Timestamptz          | Auto-set                                                                                  |
| updated_at       | Timestamptz          | Auto-updated                                                                              |

### lead_events

Audit trail for every state change.

| Column     | Type               | Description                                               |
| ---------- | ------------------ | --------------------------------------------------------- |
| id         | UUID (PK)          |                                                           |
| lead_id    | UUID (FK -> leads) | Indexed                                                   |
| event_type | Text               | e.g., `auto_approved`, `crm_synced`, `duplicate_detected` |
| payload    | JSONB              | Event-specific metadata                                   |
| created_at | Timestamptz        |                                                           |

### workflow_runs

Per-step tracking for the processing pipeline.

| Column         | Type               | Description                                                    |
| -------------- | ------------------ | -------------------------------------------------------------- |
| id             | UUID (PK)          |                                                                |
| lead_id        | UUID (FK -> leads) | Indexed                                                        |
| step_name      | Text               | `extract`, `validate`, `score`, `branch`, `crm_sync`, `notify` |
| status         | Enum               | `pending`, `running`, `succeeded`, `failed`, `skipped`         |
| input_payload  | JSONB              | Step input                                                     |
| output_payload | JSONB              | Step output                                                    |
| error_message  | Text               | Error details if failed                                        |
| attempt_number | Integer            | Retry count (default 1)                                        |
| created_at     | Timestamptz        |                                                                |

### dedupe_keys

Multi-strategy deduplication index.

| Column    | Type               | Description                                                               |
| --------- | ------------------ | ------------------------------------------------------------------------- |
| id        | UUID (PK)          |                                                                           |
| lead_id   | UUID (FK -> leads) |                                                                           |
| key_type  | Enum               | `email_exact`, `phone_normalized`, `company_name_fuzzy`, `composite_hash` |
| key_value | Text, indexed      | Normalized key value                                                      |
|           | UNIQUE             | Constraint on `(key_type, key_value)`                                     |

### users

Dashboard users with role-based access.

| Column          | Type      | Description                    |
| --------------- | --------- | ------------------------------ |
| id              | UUID (PK) |                                |
| name            | Text      |                                |
| email           | Text      |                                |
| hashed_password | Text      | bcrypt hash via passlib        |
| role            | Enum      | `admin`, `sales_rep`, `viewer` |

---

## API Endpoints

### Auth

| Method | Path             | Auth | Description              |
| ------ | ---------------- | ---- | ------------------------ |
| POST   | `/auth/register` | None | Register a new user      |
| POST   | `/auth/login`    | None | Login, returns JWT token |

### Webhook & Ingestion

| Method | Path             | Auth                      | Description                                                            |
| ------ | ---------------- | ------------------------- | ---------------------------------------------------------------------- |
| POST   | `/webhooks/lead` | API Key + Idempotency Key | Receive lead from external source. Rate-limited (60/min). Returns 202. |
| POST   | `/leads/upload`  | JWT                       | Upload CSV file (max 10MB). Async processing via Celery.               |

### Lead Management

| Method | Path                  | Auth | Description                                                       |
| ------ | --------------------- | ---- | ----------------------------------------------------------------- |
| GET    | `/leads`              | JWT  | List leads with filtering (status, source, intent) and pagination |
| GET    | `/leads/{id}`         | JWT  | Lead detail with extracted fields, confidence, raw payload        |
| PATCH  | `/leads/{id}`         | JWT  | Manually correct extracted fields                                 |
| POST   | `/leads/{id}/approve` | JWT  | Approve a `needs_review` lead, triggers CRM sync                  |
| GET    | `/leads/{id}/events`  | JWT  | Audit trail for a specific lead                                   |

### Workflow Operations

| Method | Path                        | Auth | Description                                 |
| ------ | --------------------------- | ---- | ------------------------------------------- |
| GET    | `/workflow-runs`            | JWT  | List runs, filterable by lead_id and status |
| GET    | `/workflow-runs/{id}`       | JWT  | Detail of a specific run                    |
| POST   | `/workflow-runs/{id}/retry` | JWT  | Retry a specific failed step                |

### Observability

| Method | Path       | Auth | Description                                                               |
| ------ | ---------- | ---- | ------------------------------------------------------------------------- |
| GET    | `/metrics` | JWT  | Aggregated stats: totals, rates, avg latency, breakdowns by source/intent |
| GET    | `/health`  | None | Health check (`{"status": "ok"}`)                                         |

### Internal (for n8n)

| Method | Path                  | Description                               |
| ------ | --------------------- | ----------------------------------------- |
| POST   | `/internal/normalize` | Normalize raw payload to canonical schema |
| POST   | `/internal/extract`   | LLM extraction                            |
| POST   | `/internal/validate`  | Schema validation + dedup check           |
| POST   | `/internal/enrich`    | Company enrichment lookup                 |
| POST   | `/internal/crm-sync`  | Create/update HubSpot contact             |
| POST   | `/internal/log`       | Persist workflow_run record               |

---

## Lead Processing Pipeline

When a lead is received via webhook or CSV, it enters the Celery pipeline (`process_lead_pipeline`):

```
1. EXTRACT    -> LLM extracts structured fields from raw_payload via OpenRouter
                 Returns: name, email, company, phone, title, intent, confidence_score

2. VALIDATE   -> Schema validation + deduplication check
                 4 strategies: email exact, phone normalized, company+name fuzzy, composite hash
                 Duplicates are rejected immediately

3. SCORE      -> Rule-based scoring (0-100)
                 Factors: intent weight, title seniority, company email domain, presence bonuses

4. BRANCH     -> Confidence-based routing
                 >= 0.85 confidence -> auto-approve, continue to CRM sync
                 <  0.85 confidence -> set to "needs_review", notify Slack, wait for human approval

5. CRM SYNC   -> Create or update HubSpot contact
                 Handles 409 conflicts (search + update), 429 rate limits

6. NOTIFY     -> Send Slack message to sales channel
```

Each step logs its status to the `workflow_runs` table (pending -> running -> succeeded/failed). Failed steps retry up to 3 times with exponential backoff.

---

## Services

### Extraction (`app/services/extraction.py`)

Uses OpenRouter (OpenAI-compatible API) with free models. Since free models don't reliably support function calling, extraction uses prompt-based JSON output with manual parsing:

- **Prompt**: Instructs the LLM to return structured JSON with name, email, company, phone, title, intent, and confidence_score
- **Parsing**: `_parse_llm_response()` strips markdown code fences (`json ... `), deserializes JSON, validates intent enum values
- **Fallback**: If no API key is configured or LLM call fails, `_fallback_extraction()` maps known keys directly from the raw payload with confidence 0.3
- **Model**: `meta-llama/llama-3.1-8b-instruct:free` (configurable)

### Deduplication (`app/services/dedup.py`)

Four strategies run in sequence. If any match is found against a different lead, the new lead is flagged as a duplicate:

1. **Email exact match**: Lowercased, trimmed
2. **Phone normalized**: Parsed via `phonenumbers` library, formatted to E.164
3. **Company + name fuzzy**: SHA-256 hash of `company|name` (lowercased)
4. **Composite hash**: SHA-256 hash of `email|phone|company`

All keys are registered in the `dedupe_keys` table with a UNIQUE constraint on `(key_type, key_value)`.

### Scoring (`app/services/scoring.py`)

Rule-based engine computing a 0-100 score:

| Factor                    | Points |
| ------------------------- | ------ |
| Intent: demo_request      | 40     |
| Intent: pricing_inquiry   | 35     |
| Intent: partnership       | 30     |
| Intent: general_inquiry   | 15     |
| Intent: support           | 10     |
| Intent: unknown           | 5      |
| Title seniority: C-level  | 30     |
| Title seniority: VP       | 25     |
| Title seniority: Director | 20     |
| Title seniority: Manager  | 15     |
| Company present           | 10     |
| Business email domain     | 15     |
| Phone present             | 5      |

Score is capped at 100.

### CRM Sync (`app/services/crm.py`)

HubSpot integration:

- **Create**: POST to `/crm/v3/objects/contacts` with mapped fields (firstname, lastname, company, phone, jobtitle)
- **409 Conflict**: Search for existing contact by email, then PATCH to update
- **429 Rate Limit**: Logged and returned as failure for retry
- **Mock mode**: When no `HUBSPOT_ACCESS_TOKEN` is set, returns a mock CRM ID (for development)

### Notifications (`app/services/notification.py`)

Slack webhook notifications with different message templates per event type (new_lead, needs_review, etc.).

### Enrichment (`app/services/enrichment.py`)

Stub service that extracts company domain from email address. Designed to be extended with Clearbit/Apollo in the future.

---

## Admin Dashboard

A single-file dark-themed admin dashboard served at `/` (`frontend/index.html`). Built with vanilla HTML + JS + CSS (no build step required).

**Features:**

- **Auth screen**: Login/register with JWT token management
- **Dashboard**: Metrics grid (total leads, approval rate, failure rate, avg latency), leads by source/intent
- **Leads inbox**: Table with status badges, source indicators, filtering by status/source/intent, pagination
- **Lead detail**: Before/after comparison (raw payload vs. structured output), workflow step timeline with durations and error details, event audit log
- **Approval flow**: One-click approve for `needs_review` leads
- **Workflow runs**: List with per-step status, retry button for failed steps
- **CSV upload**: Modal for uploading CSV files
- **Test lead**: Modal for submitting test leads via webhook

---

## n8n Integration

n8n acts as an optional visual workflow orchestrator. All business logic lives in FastAPI -- n8n simply calls the internal endpoints in sequence:

```
Trigger -> POST /internal/normalize
        -> POST /internal/extract
        -> POST /internal/validate
        -> IF confidence >= 0.85
            -> POST /internal/crm-sync
        -> ELSE
            -> Set needs_review
        -> Slack notification
        -> POST /internal/log
```

n8n is included in the Docker Compose stack at `http://localhost:5678` (user: `admin`, password: `admin`).

---

## Getting Started

### Prerequisites

- Python 3.11+
- Docker and Docker Compose (for infrastructure services)

### 1. Clone and set up environment

```bash
# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your actual values:
#   - OPENROUTER_API_KEY (get a free key at https://openrouter.ai)
#   - HUBSPOT_ACCESS_TOKEN (optional, mock mode works without it)
#   - SLACK_WEBHOOK_URL (optional)
```

### 3. Start infrastructure

```bash
docker compose up -d postgres redis minio n8n
```

### 4. Run database migrations

```bash
alembic upgrade head
```

### 5. Start the API server

```bash
uvicorn app.main:app --reload --port 8000
```

### 6. Start the Celery worker (separate terminal)

```bash
celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
```

### 7. Access the dashboard

Open `http://localhost:8000` in your browser. Register a user and log in.

### Full stack via Docker Compose

Alternatively, run everything with one command:

```bash
docker compose up --build
```

This starts: API (port 8000), Celery worker, PostgreSQL (5432), Redis (6379), MinIO (9000/9001), n8n (5678).

---

## Configuration

All configuration is via environment variables (loaded from `.env` file). See `.env.example` for the full list.

| Variable               | Default                                 | Description                                                       |
| ---------------------- | --------------------------------------- | ----------------------------------------------------------------- |
| `SECRET_KEY`           | `change-me-in-production`               | JWT signing key                                                   |
| `API_KEY`              | `dev-webhook-api-key`                   | Webhook API key (X-API-Key header)                                |
| `DATABASE_URL`         | `postgresql+asyncpg://...`              | Async PostgreSQL connection                                       |
| `REDIS_URL`            | `redis://localhost:6379/0`              | Redis for caching/idempotency                                     |
| `CELERY_BROKER_URL`    | `redis://localhost:6379/1`              | Celery broker                                                     |
| `OPENROUTER_API_KEY`   | (empty)                                 | OpenRouter API key. Falls back to passthrough extraction if empty |
| `OPENROUTER_BASE_URL`  | `https://openrouter.ai/api/v1`          | OpenRouter endpoint                                               |
| `OPENROUTER_MODEL`     | `meta-llama/llama-3.1-8b-instruct:free` | LLM model (free tier)                                             |
| `HUBSPOT_ACCESS_TOKEN` | (empty)                                 | HubSpot API token. Returns mock IDs if empty                      |
| `SLACK_WEBHOOK_URL`    | (empty)                                 | Slack incoming webhook URL                                        |
| `CONFIDENCE_THRESHOLD` | `0.85`                                  | Min confidence for auto-approval                                  |
| `WEBHOOK_RATE_LIMIT`   | `60/minute`                             | Rate limit on webhook endpoint                                    |
| `LLM_TIMEOUT_SECONDS`  | `30`                                    | Timeout for LLM API calls                                         |
| `CRM_TIMEOUT_SECONDS`  | `15`                                    | Timeout for HubSpot API calls                                     |

---

## Running Tests

```bash
# Run all pure unit tests (no database required)
pytest tests/test_scoring.py tests/test_extraction.py tests/test_dedup.py -v -k "not async"

# Run all tests (requires PostgreSQL)
pytest -v

# Run with coverage
pytest --cov=app --cov-report=term-missing
```

**Test coverage:**

- `test_scoring.py` (5 tests): Score computation edge cases -- unknown/minimal, demo request + company email, C-level title, cap at 100, free email penalty
- `test_extraction.py` (7 tests): JSON parsing (clean, markdown-fenced, invalid, unknown intent), fallback extraction, mocked OpenRouter call
- `test_dedup.py` (8 tests): Email normalization, phone normalization (valid/invalid), fuzzy company key, composite hash determinism/uniqueness, 2 async DB tests
- `test_webhooks.py` (4 tests): Webhook endpoint validation, auth, idempotency
- `test_leads.py` (8 tests): CRUD operations, filtering, approval flow

### Lint

```bash
ruff check .
```

---

## Docker Compose Stack

| Service  | Image               | Port       | Purpose                            |
| -------- | ------------------- | ---------- | ---------------------------------- |
| api      | Custom (Dockerfile) | 8000       | FastAPI server with hot reload     |
| worker   | Custom (Dockerfile) | --         | Celery worker (2 concurrent tasks) |
| postgres | postgres:16-alpine  | 5432       | Primary data store                 |
| redis    | redis:7-alpine      | 6379       | Broker + cache                     |
| minio    | minio/minio         | 9000, 9001 | S3-compatible file storage         |
| n8n      | n8nio/n8n           | 5678       | Visual workflow orchestrator       |

All services have health checks configured. Data is persisted in named Docker volumes (`pgdata`, `miniodata`, `n8ndata`).
