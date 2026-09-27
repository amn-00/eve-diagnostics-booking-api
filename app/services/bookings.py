from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, InvalidRequest, NotFound
from app.models import Booking, BookingStatus, Centre, CentreTest, DiagnosticTest, User, UserRole
from app.schemas import BookingIn

# Only these moves are allowed. FAILED and CANCELLED are terminal - if a payment
# fails the user makes a new booking instead of re-using the old one.
ALLOWED_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.PENDING: {BookingStatus.CONFIRMED, BookingStatus.FAILED, BookingStatus.CANCELLED},
    BookingStatus.CONFIRMED: {BookingStatus.CANCELLED},
    BookingStatus.FAILED: set(),
    BookingStatus.CANCELLED: set(),
}


def can_transition(current: BookingStatus, new: BookingStatus) -> bool:
    return new in ALLOWED_TRANSITIONS[current]


def transition(booking: Booking, new: BookingStatus) -> None:
    if not can_transition(booking.status, new):
        raise Conflict(f"Booking is {booking.status.value} and can't be moved to {new.value}")
    booking.status = new


def get_booking_for_user(db: Session, booking_id: int, user: User, *, lock: bool = False) -> Booking:
    query = select(Booking).where(Booking.id == booking_id)
    if lock:
        query = query.with_for_update()
    booking = db.scalar(query)

    if booking is None:
        raise NotFound("Booking not found")
    if booking.user_id != user.id and user.role != UserRole.ADMIN:
        raise Forbidden("You don't have access to this booking")
    return booking


def create_booking(db: Session, user: User, data: BookingIn) -> Booking:
    offering = db.get(CentreTest, (data.centre_id, data.test_id))
    if offering is None:
        if db.get(Centre, data.centre_id) is None:
            raise NotFound("Centre not found")
        if db.get(DiagnosticTest, data.test_id) is None:
            raise NotFound("Test not found")
        raise InvalidRequest("This centre doesn't offer the selected test")

    # stop the same user from booking the exact same slot twice
    duplicate = db.scalar(
        select(Booking.id).where(
            Booking.user_id == user.id,
            Booking.centre_id == data.centre_id,
            Booking.test_id == data.test_id,
            Booking.appointment_at == data.appointment_at,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
        )
    )
    if duplicate is not None:
        raise Conflict(f"You already have an active booking for this slot (booking {duplicate})")

    booking = Booking(
        user_id=user.id,
        centre_id=data.centre_id,
        test_id=data.test_id,
        appointment_at=data.appointment_at,
        amount=offering.price,
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


def cancel_booking(db: Session, booking_id: int, user: User) -> Booking:
    booking = get_booking_for_user(db, booking_id, user, lock=True)
    if booking.user_id != user.id:
        # admins can view any booking but only the patient can cancel it
        raise Forbidden("Only the patient can cancel this booking")

    transition(booking, BookingStatus.CANCELLED)
    db.commit()
    db.refresh(booking)
    return booking
