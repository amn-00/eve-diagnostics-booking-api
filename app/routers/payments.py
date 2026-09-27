import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status

from app.config import settings
from app.deps import DB, CurrentUser
from app.errors import Unauthorized
from app.schemas import PaymentIn, PaymentOut, PaymentResult, WebhookIn, WebhookOut
from app.services import payments as payment_service

router = APIRouter(prefix="/payments", tags=["payments"])


def sign_payload(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def verify_webhook_signature(
    request: Request,
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
) -> None:
    """The provider signs the raw body with the shared secret (HMAC-SHA256).
    Without this anyone could POST a fake SUCCESS and confirm a booking for free."""
    body = await request.body()
    expected = sign_payload(body, settings.webhook_secret)
    if not x_signature or not hmac.compare_digest(expected, x_signature):
        raise Unauthorized("Invalid webhook signature")


@router.post(
    "/",
    response_model=PaymentResult,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Replay of an earlier request with the same Idempotency-Key"}},
)
def make_payment(
    data: PaymentIn,
    response: Response,
    db: DB,
    user: CurrentUser,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=100)] = None,
):
    """Simulated payment. Result is SUCCESS or FAILED and the booking is updated to match.

    Send an `Idempotency-Key` header to make retries safe - repeating the request
    with the same key returns the original payment instead of charging again.
    """
    payment, created = payment_service.create_payment(
        db, user, data.booking_id, simulate=data.simulate, idempotency_key=idempotency_key
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return PaymentResult(payment=PaymentOut.model_validate(payment), booking_status=payment.booking.status)


@router.post(
    "/webhook/",
    response_model=WebhookOut,
    dependencies=[Depends(verify_webhook_signature)],
)
def payment_webhook(data: WebhookIn, db: DB):
    """Payment status updates from the provider. Idempotent on `event_id`:
    sending the same event again returns `"status": "duplicate"` and changes nothing."""
    return payment_service.process_webhook(db, data)
