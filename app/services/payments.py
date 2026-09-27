import logging
import random
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import Conflict, Forbidden, InvalidRequest, NotFound
from app.models import (
    Booking,
    BookingStatus,
    Payment,
    PaymentSource,
    PaymentStatus,
    User,
    WebhookEvent,
)
from app.schemas import WebhookIn
from app.services.bookings import can_transition, get_booking_for_user

log = logging.getLogger(__name__)


def _booking_status_for(payment_status: PaymentStatus) -> BookingStatus:
    return BookingStatus.CONFIRMED if payment_status == PaymentStatus.SUCCESS else BookingStatus.FAILED


def _apply_to_booking(booking: Booking, payment_status: PaymentStatus) -> bool:
    """Move the booking based on a payment result. Returns True if the booking changed.

    Both POST /payments/ and the webhook go through here so they can't disagree
    about what a payment result means for a booking.
    """
    target = _booking_status_for(payment_status)
    if booking.status == target or not can_transition(booking.status, target):
        return False
    booking.status = target
    return True


def _simulate_gateway(simulate: str | None) -> PaymentStatus:
    if simulate == "success":
        return PaymentStatus.SUCCESS
    if simulate == "failure":
        return PaymentStatus.FAILED
    return PaymentStatus.SUCCESS if random.random() < settings.payment_success_rate else PaymentStatus.FAILED


def _new_provider_ref() -> str:
    return f"pay_{uuid.uuid4().hex[:20]}"


def create_payment(
    db: Session,
    user: User,
    booking_id: int,
    simulate: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[Payment, bool]:
    """Runs a mock payment for a booking. Returns (payment, created).

    If the same Idempotency-Key is sent again we return the original payment
    instead of charging twice (created=False).
    """
    # lock the booking row so two payment requests for it can't both go through
    booking = get_booking_for_user(db, booking_id, user, lock=True)
    if booking.user_id != user.id:
        raise Forbidden("You can only pay for your own bookings")

    if idempotency_key:
        existing = db.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
        if existing is not None:
            if existing.booking_id != booking.id:
                raise InvalidRequest("This Idempotency-Key was already used for a different booking")
            return existing, False

    if booking.status != BookingStatus.PENDING:
        raise Conflict(f"Booking is {booking.status.value}, only PENDING bookings can be paid")

    result = _simulate_gateway(simulate)
    payment = Payment(
        booking_id=booking.id,
        amount=booking.amount,
        status=result,
        source=PaymentSource.API,
        provider_ref=_new_provider_ref(),
        idempotency_key=idempotency_key,
    )
    db.add(payment)
    _apply_to_booking(booking, result)

    try:
        db.commit()
    except IntegrityError:
        # same key used concurrently for another booking
        db.rollback()
        raise Conflict("This Idempotency-Key is already in use")

    db.refresh(payment)
    log.info(
        "payment processed",
        extra={"booking_id": booking.id, "payment_id": payment.id, "result": result.value},
    )
    return payment, True


def process_webhook(db: Session, data: WebhookIn) -> dict:
    """Applies a payment-status event from the provider. Safe to call any number of times.

    The event row is inserted first, in the same transaction as everything else.
    event_id is unique, so a replayed event fails on insert and we return early -
    this holds even if two copies arrive at the same moment, since the database
    makes the second insert wait for the first transaction and then fail.
    """
    event = WebhookEvent(
        event_id=data.event_id,
        booking_id=None,
        payload=data.model_dump(mode="json"),
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        log.info("duplicate webhook ignored", extra={"event_id": data.event_id})
        return {"status": "duplicate", "event_id": data.event_id}

    booking = db.scalar(select(Booking).where(Booking.id == data.booking_id).with_for_update())
    if booking is None:
        # nothing gets saved, so if the provider retries later it's processed properly
        db.rollback()
        raise NotFound("Booking not found")

    if data.amount is not None and data.amount != booking.amount:
        db.rollback()
        raise InvalidRequest("Amount doesn't match the booking amount")

    event.booking_id = booking.id
    status = PaymentStatus(data.status)
    payment = db.scalar(select(Payment).where(Payment.provider_ref == data.payment_ref))

    if payment is not None and payment.booking_id != booking.id:
        db.rollback()
        raise InvalidRequest("payment_ref belongs to a different booking")

    if payment is not None:
        # we already know this payment (e.g. from POST /payments/ or an earlier event).
        # Payment results are final, so a different status here is logged, not applied.
        if payment.status == status:
            event.outcome = "no_change"
        else:
            event.outcome = "status_mismatch_ignored"
            log.warning(
                "webhook status differs from recorded payment",
                extra={"payment_ref": data.payment_ref, "recorded": payment.status.value, "received": status.value},
            )
    else:
        db.add(
            Payment(
                booking_id=booking.id,
                amount=booking.amount,
                status=status,
                source=PaymentSource.WEBHOOK,
                provider_ref=data.payment_ref,
            )
        )
        if _apply_to_booking(booking, status):
            event.outcome = "applied"
        else:
            event.outcome = "booking_not_pending"
            if status == PaymentStatus.SUCCESS:
                # money was taken for a booking we can't confirm anymore -> needs a refund
                log.warning(
                    "successful payment for non-pending booking, needs refund",
                    extra={"booking_id": booking.id, "booking_status": booking.status.value},
                )

    try:
        db.commit()
    except IntegrityError:
        # a different event with the same payment_ref got in first; a retry will see it
        db.rollback()
        raise Conflict("Payment is being processed by another event, retry later")

    log.info(
        "webhook processed",
        extra={"event_id": data.event_id, "booking_id": booking.id, "outcome": event.outcome},
    )
    return {
        "status": "processed",
        "event_id": data.event_id,
        "outcome": event.outcome,
        "booking_status": booking.status,
    }
