import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ADMIN_PASSWORD", "testpass")
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("JOBS_DIR", "/tmp/docx-engineer-test-jobs")

from app.main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=True)


def test_login_wrong_password():
    resp = client.post("/api/auth/login", json={"password": "wrong"})
    assert resp.status_code == 401


def test_login_correct_password():
    resp = client.post("/api/auth/login", json={"password": "testpass"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "session" in resp.cookies


def test_me_unauthenticated():
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_authenticated():
    login = client.post("/api/auth/login", json={"password": "testpass"})
    assert login.status_code == 200
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["user"] == "admin"


def test_logout():
    client.post("/api/auth/login", json={"password": "testpass"})
    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
