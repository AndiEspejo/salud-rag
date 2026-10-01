"""HTTP API for the salud-rag assistant."""

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="salud-rag",
    description="Spanish informational health assistant with cited sources. Not medical advice.",
    version="0.1.0",
)


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness check."""
    return HealthResponse(status="ok")
