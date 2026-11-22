from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

# Fresh DB for tests
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

client = TestClient(app)

def test_health():
    assert client.get("/health").status_code == 200

def test_create_job():
    r = client.post("/jobs", json={"type": "send_email", "payload": {"to": "a@b.com"}, "idempotency_key": "t-1"})
    assert r.status_code == 201
    assert r.json()["status"] in ("queued", "completed")

def test_idempotency():
    r1 = client.post("/jobs", json={"type": "send_email", "payload": {}, "idempotency_key": "dup-1"})
    r2 = client.post("/jobs", json={"type": "send_email", "payload": {}, "idempotency_key": "dup-1"})
    assert r1.json()["id"] == r2.json()["id"]

def test_cancel():
    r = client.post("/jobs", json={"type": "send_email", "payload": {}, "scheduled_at": "2030-01-01T00:00:00", "idempotency_key": "cancel-1"})
    jid = r.json()["id"]
    c = client.post(f"/jobs/{jid}/cancel")
    assert c.json()["status"] == "cancelled"

def test_persistence():
    r = client.post("/jobs", json={"type": "send_email", "payload": {}, "idempotency_key": "persist-1"})
    jid = r.json()["id"]
    g = client.get(f"/jobs/{jid}")
    assert g.status_code == 200
    assert g.json()["id"] == jid