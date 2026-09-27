from datetime import timedelta

from app.security import create_access_token


def test_signup_returns_user_without_password(client):
    r = client.post(
        "/auth/signup",
        json={"email": "Aman@Gmail.com", "password": "password123", "full_name": "Aman"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "aman@gmail.com"  # normalised
    assert body["role"] == "USER"
    assert "password" not in body and "password_hash" not in body


def test_signup_duplicate_email_is_case_insensitive(client):
    payload = {"email": "aman@gmail.com", "password": "password123", "full_name": "Aman"}
    assert client.post("/auth/signup", json=payload).status_code == 201

    payload["email"] = "AMAN@gmail.com"
    r = client.post("/auth/signup", json=payload)
    assert r.status_code == 409


def test_signup_validation(client):
    assert client.post(
        "/auth/signup", json={"email": "not-an-email", "password": "password123", "full_name": "A"}
    ).status_code == 422
    assert client.post(
        "/auth/signup", json={"email": "a@gmail.com", "password": "short", "full_name": "A"}
    ).status_code == 422
    assert client.post(
        "/auth/signup", json={"email": "a@gmail.com", "password": "password123", "full_name": "   "}
    ).status_code == 422
    assert client.post("/auth/signup", json={}).status_code == 422


def test_login_and_me(client, user_headers):
    r = client.get("/auth/me", headers=user_headers)
    assert r.status_code == 200
    assert r.json()["email"] == "aman@gmail.com"


def test_login_wrong_password(client, user_headers):
    r = client.post("/auth/login", json={"email": "aman@gmail.com", "password": "wrongpassword"})
    assert r.status_code == 401


def test_login_unknown_email_gives_same_error(client):
    r = client.post("/auth/login", json={"email": "nobody@gmail.com", "password": "password123"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


def test_protected_route_without_token(client):
    assert client.get("/auth/me").status_code == 401


def test_protected_route_with_garbage_token(client):
    r = client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_expired_token_rejected(client, user_headers):
    token = create_access_token(1, expires_in=timedelta(seconds=-1))
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
