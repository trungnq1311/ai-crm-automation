from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "ai-crm-automation"
    debug: bool = False
    secret_key: str = "change-me-in-production"
    api_key: str = "dev-webhook-api-key"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_crm"
    database_url_sync: str = "postgresql://postgres:postgres@localhost:5432/ai_crm"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/1"

    # LLM (OpenRouter — OpenAI-compatible API, free models)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "meta-llama/llama-3.1-8b-instruct:free"

    # HubSpot
    hubspot_access_token: str = ""

    # Slack
    slack_webhook_url: str = ""

    # S3 / MinIO
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_name: str = "lead-uploads"

    # JWT
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 480

    # Pipeline
    confidence_threshold: float = 0.85
    max_retry_attempts: int = 3
    llm_timeout_seconds: int = 30
    crm_timeout_seconds: int = 15
    enrichment_timeout_seconds: int = 10
    webhook_rate_limit: str = "60/minute"
    idempotency_key_ttl_seconds: int = 86400  # 24h

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
