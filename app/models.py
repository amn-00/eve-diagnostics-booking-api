import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    USER = "USER"
    ADMIN = "ADMIN"


class BookingStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PaymentSource(str, enum.Enum):
    API = "API"
    WEBHOOK = "WEBHOOK"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), default=UserRole.USER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Centre(Base):
    __tablename__ = "centres"
    __table_args__ = (UniqueConstraint("name", "city", name="uq_centre_name_city"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    city: Mapped[str] = mapped_column(String(100), index=True)
    address: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    offerings: Mapped[list["CentreTest"]] = relationship(
        back_populates="centre", order_by="CentreTest.test_id"
    )


class DiagnosticTest(Base):
    __tablename__ = "diagnostic_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class CentreTest(Base):
    """A test offered at a centre. Price lives here since it differs between centres."""

    __tablename__ = "centre_tests"
    __table_args__ = (CheckConstraint("price > 0", name="ck_centre_test_price_positive"),)

    centre_id: Mapped[int] = mapped_column(ForeignKey("centres.id"), primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_tests.id"), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    centre: Mapped[Centre] = relationship(back_populates="offerings")
    test: Mapped[DiagnosticTest] = relationship()


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        # a booking can only point at a (centre, test) pair that actually exists
        ForeignKeyConstraint(
            ["centre_id", "test_id"],
            ["centre_tests.centre_id", "centre_tests.test_id"],
            name="fk_booking_centre_test",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centres.id"))
    test_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_tests.id"))
    appointment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # copied from centre_tests.price when the booking is made
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status"), default=BookingStatus.PENDING, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship()
    centre: Mapped[Centre] = relationship()
    test: Mapped[DiagnosticTest] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="booking", order_by="Payment.id")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus, name="payment_status"))
    source: Mapped[PaymentSource] = mapped_column(Enum(PaymentSource, name="payment_source"))
    # id of the payment on the provider side
    provider_ref: Mapped[str] = mapped_column(String(64), unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    booking: Mapped[Booking] = relationship(back_populates="payments")


class WebhookEvent(Base):
    """Every webhook event we've processed. The unique event_id is what makes the webhook idempotent."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(100), unique=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"))
    payload: Mapped[dict] = mapped_column(JSON)
    outcome: Mapped[str | None] = mapped_column(String(50))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
