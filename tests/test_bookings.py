from datetime import datetime, timedelta, timezone

import pytest

from app.models import BookingStatus
from app.services.bookings import can_transition
from tests.conftest import future_time


def booking_payload(catalog, **overrides):
    payload = {
        "centre_id": catalog["centre"]["id"],
        "test_id": catalog["test"]["id"],
        "appointment_at": future_time(),
    }
    payload.update(overrides)
    return payload


def test_create_booking(booking, catalog):
    assert booking["status"] == "PENDING"
    assert booking["amount"] == "499.00"
    assert booking["centre"]["id"] == catalog["centre"]["id"]
    assert booking["test"]["name"] == "Complete Blood Count"


def test_booking_keeps_price_it_was_made_at(client, admin_headers, user_headers, booking, catalog):
    r = client.patch(
        f"/centres/{catalog['centre']['id']}/tests/{catalog['test']['id']}",
        json={"price": "650.00"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    r = client.get(f"/bookings/{booking['id']}", headers=user_headers)
    assert r.json()["amount"] == "499.00"


def test_booking_requires_auth(client, catalog):
    assert client.post("/bookings/", json=booking_payload(catalog)).status_code == 401


def test_centre_must_offer_the_test(client, user_headers, catalog):
    r = client.post(
        "/bookings/",
        json=booking_payload(catalog, test_id=catalog["not_offered_test"]["id"]),
        headers=user_headers,
    )
    assert r.status_code == 422
    assert "doesn't offer" in r.json()["detail"]


def test_unknown_centre_or_test(client, user_headers, catalog):
    r = client.post("/bookings/", json=booking_payload(catalog, centre_id=999), headers=user_headers)
    assert r.status_code == 404
    r = client.post("/bookings/", json=booking_payload(catalog, test_id=999), headers=user_headers)
    assert r.status_code == 404


@pytest.mark.parametrize(
    "appointment_at",
    [
        (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),  # past
        (datetime.now() + timedelta(days=1)).replace(microsecond=0).isoformat(),  # no timezone
        "tomorrow",
    ],
)
def test_bad_appointment_time(client, user_headers, catalog, appointment_at):
    r = client.post(
        "/bookings/", json=booking_payload(catalog, appointment_at=appointment_at), headers=user_headers
    )
    assert r.status_code == 422


def test_same_slot_cannot_be_booked_twice(client, user_headers, catalog):
    payload = booking_payload(catalog)
    assert client.post("/bookings/", json=payload, headers=user_headers).status_code == 201
    r = client.post("/bookings/", json=payload, headers=user_headers)
    assert r.status_code == 409


def test_same_slot_in_different_timezone_is_still_a_duplicate(client, user_headers, catalog):
    slot = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=2)
    ist = slot.astimezone(timezone(timedelta(hours=5, minutes=30)))
    client.post("/bookings/", json=booking_payload(catalog, appointment_at=slot.isoformat()), headers=user_headers)
    r = client.post("/bookings/", json=booking_payload(catalog, appointment_at=ist.isoformat()), headers=user_headers)
    assert r.status_code == 409


def test_can_rebook_slot_after_cancelling(client, user_headers, catalog):
    payload = booking_payload(catalog)
    first = client.post("/bookings/", json=payload, headers=user_headers).json()
    client.post(f"/bookings/{first['id']}/cancel", headers=user_headers)
    assert client.post("/bookings/", json=payload, headers=user_headers).status_code == 201


def test_users_only_see_their_own_bookings(client, user_headers, other_user_headers, booking):
    assert client.get("/bookings/", headers=other_user_headers).json()["total"] == 0
    assert client.get("/bookings/", headers=user_headers).json()["total"] == 1

    r = client.get(f"/bookings/{booking['id']}", headers=other_user_headers)
    assert r.status_code == 403


def test_admin_can_see_any_booking(client, admin_headers, booking):
    assert client.get(f"/bookings/{booking['id']}", headers=admin_headers).status_code == 200
    assert client.get("/bookings/", headers=admin_headers).json()["total"] == 1


def test_filter_bookings_by_status(client, user_headers, booking):
    assert client.get("/bookings/", params={"status": "PENDING"}, headers=user_headers).json()["total"] == 1
    assert client.get("/bookings/", params={"status": "CONFIRMED"}, headers=user_headers).json()["total"] == 0
    assert client.get("/bookings/", params={"status": "WHATEVER"}, headers=user_headers).status_code == 422


def test_missing_booking(client, user_headers):
    assert client.get("/bookings/99999", headers=user_headers).status_code == 404
    assert client.post("/bookings/99999/cancel", headers=user_headers).status_code == 404


def test_cancel_booking(client, user_headers, booking):
    r = client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"

    # already cancelled
    r = client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)
    assert r.status_code == 409


def test_cannot_cancel_someone_elses_booking(client, other_user_headers, admin_headers, booking):
    assert client.post(f"/bookings/{booking['id']}/cancel", headers=other_user_headers).status_code == 403
    assert client.post(f"/bookings/{booking['id']}/cancel", headers=admin_headers).status_code == 403


def test_state_machine():
    S = BookingStatus
    assert can_transition(S.PENDING, S.CONFIRMED)
    assert can_transition(S.PENDING, S.FAILED)
    assert can_transition(S.PENDING, S.CANCELLED)
    assert can_transition(S.CONFIRMED, S.CANCELLED)

    assert not can_transition(S.CONFIRMED, S.FAILED)
    assert not can_transition(S.CONFIRMED, S.PENDING)
    for terminal in (S.FAILED, S.CANCELLED):
        for target in S:
            assert not can_transition(terminal, target)
