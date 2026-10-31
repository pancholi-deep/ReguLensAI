from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import allowed_origins
from app.services.source_monitor import start_source_monitor_scheduler, stop_source_monitor_scheduler

app = FastAPI(
    title="ReguLens AI API",
    description="Regulatory intelligence and change impact assessment API.",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-ReguLens-Request"],
)
app.include_router(router)


@app.get("/", tags=["Root"])
def root() -> dict[str, str]:
    return {"name": "ReguLens AI API", "docs": "/docs", "health": "/api/v1/health"}



@app.on_event("startup")
def start_background_source_monitor() -> None:
    start_source_monitor_scheduler()


@app.on_event("shutdown")
def stop_background_source_monitor() -> None:
    stop_source_monitor_scheduler()
