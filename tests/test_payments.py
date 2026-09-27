from app.models import Payment
from tests.conftest import future_time


def pay(client, headers, booking_id, simulate="success", key=None):
    extra = {"Idempotency-Key": key} if key else {}
    return client.post(
        "/payments/", json={"booking_id": booking_id, "simulate": simulate}, headers={**headers, **extra}
    )


def test_successful_payment_confirms_booking(client, user_headers, booking):
    r = pay(client, user_headers, booking["id"])
    assert r.status_code == 201
    body = r.json()
    assert body["payment"]["status"] == "SUCCESS"
    assert body["payment"]["amount"] == "499.00"
    assert body["payment"]["provider_ref"].startswith("pay_")
    assert body["booking_status"] == "CONFIRMED"

    assert client.get(f"/bookings/{booking['id']}", headers=user_headers).json()["status"] == "CONFIRMED"


def test_failed_payment_marks_booking_failed(client, user_headers, booking):
    r = pay(client, user_headers, booking["id"], simulate="failure")
    assert r.status_code == 201
    assert r.json()["payment"]["status"] == "FAILED"
    assert r.json()["booking_status"] == "FAILED"


def test_random_outcome_is_one_of_the_two(client, user_headers, booking):
    r = client.post("/payments/", json={"booking_id": booking["id"]}, headers=user_headers)
    assert r.status_code == 201
    assert r.json()["payment"]["status"] in {"SUCCESS", "FAILED"}


def test_cannot_pay_twice(client, user_headers, booking):
    pay(client, user_headers, booking["id"])
    r = pay(client, user_headers, booking["id"])
    assert r.status_code == 409


def test_cannot_pay_failed_booking(client, user_headers, booking):
    pay(client, user_headers, booking["id"], simulate="failure")
    assert pay(client, user_headers, booking["id"]).status_code == 409


def test_cannot_pay_cancelled_booking(client, user_headers, booking):
    client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)
    assert pay(client, user_headers, booking["id"]).status_code == 409


def test_cannot_pay_someone_elses_booking(client, other_user_headers, booking):
    assert pay(client, other_user_headers, booking["id"]).status_code == 403


def test_pay_missing_booking(client, user_headers):
    assert pay(client, user_headers, 99999).status_code == 404


def test_payment_needs_auth(client, booking):
    assert client.post("/payments/", json={"booking_id": booking["id"]}).status_code == 401


def test_invalid_payment_request(client, user_headers):
    assert client.post("/payments/", json={}, headers=user_headers).status_code == 422
    assert client.post(
        "/payments/", json={"booking_id": 1, "simulate": "maybe"}, headers=user_headers
    ).status_code == 422
    assert client.post("/payments/", json={"booking_id": -1}, headers=user_headers).status_code == 422


def test_idempotency_key_replay_returns_same_payment(client, db, user_headers, booking):
    first = pay(client, user_headers, booking["id"], key="order-123")
    # retry with the same key - e.g. the client timed out and tried again
    second = pay(client, user_headers, booking["id"], simulate="failure", key="order-123")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["payment"]["id"] == first.json()["payment"]["id"]
    assert second.json()["payment"]["status"] == "SUCCESS"
    assert db.query(Payment).count() == 1


def test_idempotency_key_reused_for_other_booking(client, user_headers, booking, catalog):
    other = client.post(
        "/bookings/",
        json={
            "centre_id": catalog["centre"]["id"],
            "test_id": catalog["test"]["id"],
            "appointment_at": future_time(days=5),
        },
        headers=user_headers,
    ).json()
    pay(client, user_headers, booking["id"], key="same-key")
    r = pay(client, user_headers, other["id"], key="same-key")
    assert r.status_code == 422


def test_booking_payments_history(client, user_headers, other_user_headers, booking):
    pay(client, user_headers, booking["id"])
    r = client.get(f"/bookings/{booking['id']}/payments", headers=user_headers)
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert client.get(f"/bookings/{booking['id']}/payments", headers=other_user_headers).status_code == 403
