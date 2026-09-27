from datetime import datetime, timezone
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import BookingStatus, PaymentStatus, UserRole

T = TypeVar("T")

Money = Decimal  # kept as Decimal end to end, serialised as a string like "499.00"


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ---- auth ----

class SignupIn(BaseModel):
    email: EmailStr
    # bcrypt only looks at the first 72 bytes, so cap it instead of silently truncating
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("full_name can't be blank")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.lower()


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    role: UserRole


# ---- centres & tests ----

class DiagnosticTestIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)


class DiagnosticTestOut(ORMModel):
    id: int
    name: str
    description: str | None


class CentreIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    city: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=255)


class CentreOut(ORMModel):
    id: int
    name: str
    city: str
    address: str


class OfferingIn(BaseModel):
    test_id: int = Field(gt=0)
    price: Money = Field(gt=0, max_digits=10, decimal_places=2)


class PriceUpdateIn(BaseModel):
    price: Money = Field(gt=0, max_digits=10, decimal_places=2)


class OfferingOut(ORMModel):
    test: DiagnosticTestOut
    price: Money


class CentreDetailOut(CentreOut):
    tests: list[OfferingOut] = Field(validation_alias="offerings")


# ---- bookings ----

class BookingIn(BaseModel):
    centre_id: int = Field(gt=0)
    test_id: int = Field(gt=0)
    appointment_at: AwareDatetime  # must include a timezone, e.g. 2026-10-01T10:30:00+05:30

    @field_validator("appointment_at")
    @classmethod
    def must_be_in_future(cls, v: datetime) -> datetime:
        if v <= datetime.now(timezone.utc):
            raise ValueError("appointment_at must be in the future")
        return v.astimezone(timezone.utc)


class NamedRef(ORMModel):
    id: int
    name: str


class BookingOut(ORMModel):
    id: int
    status: BookingStatus
    appointment_at: datetime
    amount: Money
    centre: NamedRef
    test: NamedRef
    created_at: datetime
    updated_at: datetime


# ---- payments ----

class PaymentIn(BaseModel):
    booking_id: int = Field(gt=0)
    # lets you force the mock result; left empty it's random (see PAYMENT_SUCCESS_RATE)
    simulate: Literal["success", "failure"] | None = None


class PaymentOut(ORMModel):
    id: int
    booking_id: int
    amount: Money
    status: PaymentStatus
    provider_ref: str
    created_at: datetime


class PaymentResult(BaseModel):
    payment: PaymentOut
    booking_status: BookingStatus


class WebhookIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=100)
    payment_ref: str = Field(min_length=1, max_length=64)
    booking_id: int = Field(gt=0)
    status: Literal["SUCCESS", "FAILED"]
    amount: Money | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)


class WebhookOut(BaseModel):
    status: Literal["processed", "duplicate"]
    event_id: str
    outcome: str | None = None
    booking_status: BookingStatus | None = None
