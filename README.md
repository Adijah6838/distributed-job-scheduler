# Distributed Job Scheduler

Production-style background job system: API + Workers + SQLite.

## Architecture
Client -> FastAPI (app/main.py) -> SQLite (jobs.db) -> Workers (app/worker.py)

- app/database.py - Engine, Session
- app/models.py - jobs + job_executions
- app/schemas.py - Pydantic validation
- app/main.py - REST API: POST/GET /jobs, POST /jobs/{id}/cancel, GET /stats
- app/worker.py - 2 workers, atomic claim, exponential backoff, crash reclaim
- dashboard.html - Worker UI
- tests/test_api.py - 5 tests

## Run
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000

## Test
python -m pytest tests/test_api.py -v

## Results
- 100 jobs -> completed=102
- 5/5 pytest passed
- Duplicate submit returns same ID
- fail_once retries and completes
