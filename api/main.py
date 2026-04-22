"""FastAPI application entry point.

Run with:
    uvicorn api.main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes.jobs import router as jobs_router
from .routes.stream import router as stream_router
from .routes.approvals import router as approvals_router
from .routes.interview import router as interview_router

app = FastAPI(
    title="Enterprise Harness API",
    description="REST + SSE backend for the multi-agent orchestration harness",
    version="0.9.0",
)

# Allow Next.js dev server (port 3000) and production origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)
app.include_router(stream_router)
app.include_router(approvals_router)
app.include_router(interview_router)


@app.get("/healthz")
async def health():
    return {"status": "ok"}
