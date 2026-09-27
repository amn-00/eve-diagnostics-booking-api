import threading

import pytest

from app.models import Booking, BookingStatus, Payment, WebhookEvent
from app.schemas import WebhookIn
from app.services.payments import process_webhook
from tests.conftest import IS_POSTGRES, future_time, send_webhook


def event(booking_id, status="SUCCESS", event_id="evt_1", payment_ref="pay_ext_1", **extra):
    return {"event_id": event_id, "payment_ref": payment_ref, "booking_id": booking_id, "status": status, **extra}


def test_success_webhook_confirms_booking(client, db, booking):
    r = send_webhook(client, event(booking["id"], amount="499.00"))
    assert r.status_code == 200
    assert r.json() == {
        "status": "processed",
        "event_id": "evt_1",
        "outcome": "applied",
        "booking_status": "CONFIRMED",
    }
    payment = db.query(Payment).one()
    assert payment.provider_ref == "pay_ext_1"
    assert payment.source.value == "WEBHOOK"


def test_failed_webhook_marks_booking_failed(client, booking):
    r = send_webhook(client, event(booking["id"], status="FAILED"))
    assert r.json()["booking_status"] == "FAILED"


def test_same_event_twice_is_ignored(client, db, booking):
    first = send_webhook(client, event(booking["id"]))
    second = send_webhook(client, event(booking["id"]))

    assert first.json()["status"] == "processed"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert db.query(Payment).count() == 1
    assert db.query(WebhookEvent).count() == 1


def test_replayed_event_cannot_change_state(client, db, booking):
    """Same event_id but the body was changed - still treated as the already-processed event."""
    send_webhook(client, event(booking["id"], status="SUCCESS"))
    r = send_webhook(client, event(booking["id"], status="FAILED"))
    assert r.json()["status"] == "duplicate"
    assert db.get(Booking, booking["id"]).status == BookingStatus.CONFIRMED


def test_new_event_for_known_payment_is_a_no_op(client, db, booking):
    send_webhook(client, event(booking["id"], event_id="evt_1"))
    r = send_webhook(client, event(booking["id"], event_id="evt_2"))  # provider re-sent with new id
    assert r.json()["outcome"] == "no_change"
    assert db.query(Payment).count() == 1


def test_conflicting_status_for_known_payment_is_ignored(client, db, booking):
    send_webhook(client, event(booking["id"], event_id="evt_1", status="SUCCESS"))
    r = send_webhook(client, event(booking["id"], event_id="evt_2", status="FAILED"))
    assert r.json()["outcome"] == "status_mismatch_ignored"
    assert r.json()["booking_status"] == "CONFIRMED"


def test_webhook_for_payment_made_through_api(client, user_headers, booking):
    r = client.post("/payments/", json={"booking_id": booking["id"], "simulate": "success"}, headers=user_headers)
    ref = r.json()["payment"]["provider_ref"]

    r = send_webhook(client, event(booking["id"], payment_ref=ref))
    assert r.json()["outcome"] == "no_change"
    assert r.json()["booking_status"] == "CONFIRMED"


def test_late_failure_does_not_undo_confirmed_booking(client, booking):
    send_webhook(client, event(booking["id"], event_id="evt_1", payment_ref="pay_a", status="SUCCESS"))
    r = send_webhook(client, event(booking["id"], event_id="evt_2", payment_ref="pay_b", status="FAILED"))
    assert r.json()["outcome"] == "booking_not_pending"
    assert r.json()["booking_status"] == "CONFIRMED"


def test_success_for_cancelled_booking_is_recorded_but_not_applied(client, db, user_headers, booking):
    client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)
    r = send_webhook(client, event(booking["id"]))
    assert r.json()["outcome"] == "booking_not_pending"
    assert r.json()["booking_status"] == "CANCELLED"
    # the payment is still stored so it can be refunded
    assert db.query(Payment).count() == 1


def test_unknown_booking(client, db):
    r = send_webhook(client, event(99999))
    assert r.status_code == 404
    # not stored, so a retry after the booking exists would still be processed
    assert db.query(WebhookEvent).count() == 0


def test_amount_mismatch_rejected(client, db, booking):
    r = send_webhook(client, event(booking["id"], amount="1.00"))
    assert r.status_code == 422
    assert db.get(Booking, booking["id"]).status == BookingStatus.PENDING
    assert db.query(WebhookEvent).count() == 0


def test_payment_ref_from_another_booking(client, user_headers, booking, catalog):
    other = client.post(
        "/bookings/",
        json={"centre_id": catalog["centre"]["id"], "test_id": catalog["test"]["id"], "appointment_at": future_time(9)},
        headers=user_headers,
    ).json()
    send_webhook(client, event(booking["id"], event_id="evt_1", payment_ref="pay_x"))
    r = send_webhook(client, event(other["id"], event_id="evt_2", payment_ref="pay_x"))
    assert r.status_code == 422


def test_bad_signature(client, booking):
    r = send_webhook(client, event(booking["id"]), secret="wrong-secret")
    assert r.status_code == 401


def test_missing_signature(client, booking):
    r = client.post("/payments/webhook/", json=event(booking["id"]))
    assert r.status_code == 401


def test_invalid_payload(client):
    assert send_webhook(client, {"event_id": "evt_1"}).status_code == 422
    assert send_webhook(client, event(1, status="REFUNDED")).status_code == 422


@pytest.mark.skipif(not IS_POSTGRES, reason="needs real row locks / concurrent transactions")
def test_concurrent_duplicate_webhooks(session_factory, db, booking):
    """Fire the same event from several threads at once - only one should be applied."""
    data = WebhookIn(**event(booking["id"]))
    barrier = threading.Barrier(5)
    results = []

    def worker():
        session = session_factory()
        try:
            barrier.wait()
            results.append(process_webhook(session, data)["status"])
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == ["duplicate"] * 4 + ["processed"]
    assert db.query(Payment).count() == 1
    assert db.query(WebhookEvent).count() == 1
