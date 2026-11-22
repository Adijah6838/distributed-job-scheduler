# app/main.py
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import Base, engine, get_db
from app.models import Job
from app.schemas import JobCreate, JobResponse, JobListResponse
from app.worker import start_workers

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("scheduler.api")

Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_workers(count=2)
    logger.info("workers_started count=2")
    yield

app = FastAPI(title="Distributed Job Scheduler", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def _to_response(job: Job) -> JobResponse:
    data = {"id": job.id, "type": job.type, "payload": json.loads(job.payload or "{}"), "status": job.status, "priority": job.priority, "idempotency_key": job.idempotency_key, "max_retries": job.max_retries, "retry_count": job.retry_count, "next_retry_at": job.next_retry_at, "scheduled_at": job.scheduled_at, "locked_by": job.locked_by, "created_at": job.created_at, "updated_at": job.updated_at, "started_at": job.started_at, "completed_at": job.completed_at, "duration_seconds": job.duration_seconds, "error": job.error}
    return JobResponse(**data)

@app.get("/health")
def health():
    return {"status": "ok", "service": "distributed-job-scheduler"}

@app.post("/jobs", response_model=JobResponse, status_code=201)
def create_job(payload_in: JobCreate, db: Session = Depends(get_db)):
    if payload_in.idempotency_key:
        existing = db.query(Job).filter(Job.idempotency_key == payload_in.idempotency_key).first()
        if existing:
            logger.info(f"idempotency_hit key={payload_in.idempotency_key} job_id={existing.id}")
            return _to_response(existing)
    now = datetime.now(timezone.utc)
    sched = payload_in.scheduled_at
    if sched and sched.tzinfo is None:
        sched = sched.replace(tzinfo=timezone.utc)
    status = "scheduled" if (sched and sched > now) else "queued"
    job = Job(type=payload_in.type, payload=json.dumps(payload_in.payload), priority=payload_in.priority, idempotency_key=payload_in.idempotency_key, max_retries=payload_in.max_retries, scheduled_at=sched, status=status)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(Job).filter(Job.idempotency_key == payload_in.idempotency_key).first()
        if existing:
            return _to_response(existing)
        raise
    db.refresh(job)
    logger.info(f"job_created id={job.id} type={job.type} status={job.status} priority={job.priority}")
    return _to_response(job)

@app.get("/jobs", response_model=JobListResponse)
def list_jobs(status: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(Job)
    if status:
        q = q.filter(Job.status == status)
    jobs = q.order_by(Job.created_at.desc()).limit(limit).all()
    total = q.count()
    return JobListResponse(total=total, jobs=[_to_response(j) for j in jobs])

@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_response(job)

@app.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("queued", "scheduled"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel job in status {job.status}")
    job.status = "cancelled"
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    logger.info(f"job_cancelled id={job.id}")
    return _to_response(job)

@app.get("/stats")
def stats(db: Session = Depends(get_db)):
    from sqlalchemy import func
    rows = db.query(Job.status, func.count(Job.id)).group_by(Job.status).all()
    return {"by_status": {s: c for s, c in rows}}
