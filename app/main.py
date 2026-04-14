from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from slowapi import Limiter
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.auth import router as auth_router
from app.api.internal import router as internal_router
from app.api.leads import router as leads_router
from app.api.metrics import router as metrics_router
from app.api.webhooks import router as webhooks_router
from app.api.workflow_runs import router as workflow_runs_router
from app.config import settings
from app.logging import setup_logging

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])
app.include_router(leads_router, prefix="/leads", tags=["leads"])
app.include_router(workflow_runs_router,
                   prefix="/workflow-runs", tags=["workflow-runs"])
app.include_router(metrics_router, prefix="/metrics", tags=["metrics"])
app.include_router(internal_router, prefix="/internal", tags=["internal"])


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")
