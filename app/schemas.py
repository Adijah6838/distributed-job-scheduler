# app/schemas.py
# Pydantic schemas = the contract for our API.
# They validate incoming JSON and shape outgoing JSON.

from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class JobCreate(BaseModel):
    # Client must send a type. We only allow our 3 demo types.
    type: str = Field(..., examples=["send_email"])
    # Any JSON args for the job, e.g. {"to": "a@b.com"}
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=0, le=100)
    # Optional: if client sends the same key twice, we return the same job
    idempotency_key: Optional[str] = None
    max_retries: int = Field(default=3, ge=0, le=10)
    # Optional: run later, e.g. "2026-11-22T10:00:00"
    scheduled_at: Optional[datetime] = None

class JobResponse(BaseModel):
    id: str
    type: str
    payload: Dict[str, Any]
    status: str
    priority: int
    idempotency_key: Optional[str]
    max_retries: int
    retry_count: int
    next_retry_at: Optional[datetime]
    scheduled_at: Optional[datetime]
    locked_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[int]
    error: Optional[str]

    model_config = ConfigDict(from_attributes=True)

class JobListResponse(BaseModel):
    total: int
    jobs: list[JobResponse]