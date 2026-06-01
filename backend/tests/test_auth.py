import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ADMIN_PASSWORD", "testpass")
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("JOBS_DIR", "/tmp/docx-engineer-test-jobs")

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    # Fresh client per test — TestClient persists cookies in a shared jar, so a
    # module-level instance would leak a login session across tests.
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_login_wrong_password(client):
    resp = client.post("/api/auth/login", json={"password": "wrong"})
    assert resp.status_code == 401


def test_login_correct_password(client):
    resp = client.post("/api/auth/login", json={"password": "testpass"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "session" in resp.cookies


def test_me_unauthenticated(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_authenticated(client):
    login = client.post("/api/auth/login", json={"password": "testpass"})
    assert login.status_code == 200
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["user"] == "admin"


def test_logout(client):
    client.post("/api/auth/login", json={"password": "testpass"})
    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
