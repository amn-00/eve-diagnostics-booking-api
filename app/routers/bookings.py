from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.deps import DB, CurrentUser, Pagination, paginate
from app.models import Booking, BookingStatus, UserRole
from app.schemas import BookingIn, BookingOut, Page, PaymentOut
from app.services import bookings as booking_service

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("/", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def create_booking(data: BookingIn, db: DB, user: CurrentUser):
    return booking_service.create_booking(db, user, data)


@router.get("/", response_model=Page[BookingOut])
def list_bookings(
    db: DB,
    user: CurrentUser,
    page: Pagination,
    status_filter: BookingStatus | None = Query(None, alias="status"),
):
    """Your own bookings, newest first. Admins see everyone's."""
    query = select(Booking).order_by(Booking.id.desc())
    if user.role != UserRole.ADMIN:
        query = query.where(Booking.user_id == user.id)
    if status_filter:
        query = query.where(Booking.status == status_filter)

    return paginate(db, query, page)


@router.get("/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: int, db: DB, user: CurrentUser):
    return booking_service.get_booking_for_user(db, booking_id, user)


@router.get("/{booking_id}/payments", response_model=list[PaymentOut])
def list_booking_payments(booking_id: int, db: DB, user: CurrentUser):
    booking = booking_service.get_booking_for_user(db, booking_id, user)
    return booking.payments


@router.post("/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(booking_id: int, db: DB, user: CurrentUser):
    return booking_service.cancel_booking(db, booking_id, user)
