# app/worker.py
import json
import time
import random
import logging
import threading
from datetime import datetime, timezone, timedelta
from sqlalchemy import or_, and_
from app.database import SessionLocal
from app.models import Job, JobExecution

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("scheduler.worker")

def _utcnow():
    return datetime.now(timezone.utc)

def _execute(job_type, payload):
    # Simulated work. Replace with real logic later.
    if job_type == "send_email":
        time.sleep(1)
        return True
    if job_type == "generate_report":
        time.sleep(3)
        return True
    if job_type == "fail_once":
        # Fails on attempt 0, succeeds after retry
        if payload.get("_attempt", 0) == 0:
            raise Exception("Simulated failure - will succeed on retry")
        time.sleep(1)
        return True
    time.sleep(1)
    return True

def claim_job(db, worker_id):
    # Atomic claim: only 1 worker can get a job.
    # UPDATE ... WHERE status='queued' - DB guarantees atomicity.
    now = _utcnow()
    job = db.query(Job).filter(
        or_(Job.status == "queued", Job.status == "scheduled"),
        or_(Job.scheduled_at.is_(None), Job.scheduled_at <= now),
        or_(Job.next_retry_at.is_(None), Job.next_retry_at <= now),
    ).order_by(Job.priority.desc(), Job.created_at.asc()).first()
    if not job:
        return None
    # Try to claim it - if another worker claimed it first, rows affected = 0
    updated = db.query(Job).filter(Job.id == job.id, Job.status == job.status).update(
        {"status": "running", "locked_by": worker_id, "locked_at": now, "started_at": now, "updated_at": now},
        synchronize_session=False,
    )
    db.commit()
    if updated == 0:
        return None
    db.refresh(job)
    return job

def reclaim_stuck_jobs(db, timeout_seconds=30):
    # Worker crash recovery: running + locked long ago = stuck, put back to queued
    cutoff = _utcnow() - timedelta(seconds=timeout_seconds)
    stuck = db.query(Job).filter(Job.status == "running", Job.locked_at < cutoff).all()
    for j in stuck:
        logger.warning(f"reclaim_stuck job_id={j.id} locked_by={j.locked_by}")
        j.status = "queued"
        j.locked_by = None
        j.locked_at = None
        j.updated_at = _utcnow()
    if stuck:
        db.commit()
    return len(stuck)

def run_worker(worker_id, stop_event, poll_interval=1.0):
    logger.info(f"worker_started id={worker_id}")
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            reclaim_stuck_jobs(db)
            job = claim_job(db, worker_id)
            if not job:
                db.close()
                time.sleep(poll_interval)
                continue
            attempt = job.retry_count
            exec_row = JobExecution(job_id=job.id, attempt=attempt, status="started", worker_id=worker_id, started_at=_utcnow())
            db.add(exec_row)
            db.commit()
            start = time.time()
            logger.info(f"job_started id={job.id} type={job.type} attempt={attempt} worker={worker_id}")
            try:
                payload = json.loads(job.payload or "{}")
                payload["_attempt"] = attempt
                _execute(job.type, payload)
                duration = int(time.time() - start)
                job.status = "completed"
                job.completed_at = _utcnow()
                job.duration_seconds = duration
                job.error = None
                exec_row.status = "completed"
                exec_row.finished_at = _utcnow()
                exec_row.duration_seconds = duration
                logger.info(f"job_completed id={job.id} duration={duration}s worker={worker_id}")
            except Exception as e:
                duration = int(time.time() - start)
                exec_row.status = "failed"
                exec_row.finished_at = _utcnow()
                exec_row.duration_seconds = duration
                exec_row.error = str(e)
                job.error = str(e)
                if job.retry_count < job.max_retries:
                    # Exponential backoff: 2s, 4s, 8s...
                    backoff = 2 ** (job.retry_count + 1)
                    job.retry_count += 1
                    job.status = "queued"
                    job.next_retry_at = _utcnow() + timedelta(seconds=backoff)
                    job.locked_by = None
                    job.locked_at = None
                    logger.warning(f"job_retry id={job.id} retry={job.retry_count} backoff={backoff}s error={e}")
                else:
                    job.status = "failed"
                    job.completed_at = _utcnow()
                    job.duration_seconds = duration
                    logger.error(f"job_failed id={job.id} retries_exhausted error={e}")
            job.updated_at = _utcnow()
            db.commit()
        except Exception as e:
            logger.error(f"worker_error worker={worker_id} error={e}")
            db.rollback()
        finally:
            db.close()

def start_workers(count=2):
    stop_event = threading.Event()
    threads = []
    for i in range(count):
        t = threading.Thread(target=run_worker, args=(f"worker-{i+1}", stop_event), daemon=True)
        t.start()
        threads.append(t)
    return stop_event, threads