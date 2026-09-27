import json
import os
from datetime import datetime, timedelta, timezone

# these need to be set before the app (and its settings) get imported
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("BCRYPT_ROUNDS", "4")  # keeps the suite fast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import User, UserRole
from app.routers.payments import sign_payload

# Runs on in-memory SQLite by default so tests need no setup.
# Set TEST_DATABASE_URL to a Postgres URL to run against the real thing
# (the concurrency test only runs on Postgres).
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite://")
IS_POSTGRES = TEST_DATABASE_URL.startswith("postgresql")


@pytest.fixture(scope="session")
def engine():
    if IS_POSTGRES:
        eng = create_engine(TEST_DATABASE_URL)
    else:
        eng = create_engine(
            TEST_DATABASE_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---- helpers ----

def signup_and_login(client, email, password="password123", full_name="Test User"):
    r = client.post("/auth/signup", json={"email": email, "password": password, "full_name": full_name})
    assert r.status_code == 201, r.text
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def future_time(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()


def send_webhook(client, payload, secret=None):
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Signature": sign_payload(body, secret or settings.webhook_secret),
    }
    return client.post("/payments/webhook/", content=body, headers=headers)


@pytest.fixture()
def user_headers(client):
    return signup_and_login(client, "aman@gmail.com")


@pytest.fixture()
def other_user_headers(client):
    return signup_and_login(client, "someone.else@gmail.com")


@pytest.fixture()
def admin_headers(client, db):
    headers = signup_and_login(client, "admin@eve-healthcare.com", full_name="Admin")
    admin = db.query(User).filter_by(email="admin@eve-healthcare.com").one()
    admin.role = UserRole.ADMIN
    db.commit()
    return headers


@pytest.fixture()
def catalog(client, admin_headers):
    """One centre offering one test at 499.00, plus a second test it doesn't offer."""
    centre = client.post(
        "/centres/",
        json={"name": "Eve Diagnostics Sector 62", "city": "Noida", "address": "A-12, Sector 62"},
        headers=admin_headers,
    ).json()
    cbc = client.post("/tests/", json={"name": "Complete Blood Count"}, headers=admin_headers).json()
    mri = client.post("/tests/", json={"name": "MRI Brain"}, headers=admin_headers).json()
    r = client.post(
        f"/centres/{centre['id']}/tests",
        json={"test_id": cbc["id"], "price": "499.00"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return {"centre": centre, "test": cbc, "not_offered_test": mri}


@pytest.fixture()
def booking(client, user_headers, catalog):
    r = client.post(
        "/bookings/",
        json={
            "centre_id": catalog["centre"]["id"],
            "test_id": catalog["test"]["id"],
            "appointment_at": future_time(),
        },
        headers=user_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()
