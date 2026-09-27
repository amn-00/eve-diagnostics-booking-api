"""Pretends to be the payment provider and sends a signed webhook.

    python scripts/send_webhook.py --booking 1 --status SUCCESS
    python scripts/send_webhook.py --booking 1 --status SUCCESS --event-id evt_abc   # run twice to see idempotency
"""
import argparse
import hashlib
import hmac
import json
import os
import uuid

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--booking", type=int, required=True)
    parser.add_argument("--status", choices=["SUCCESS", "FAILED"], default="SUCCESS")
    parser.add_argument("--event-id", default=None)
    parser.add_argument("--payment-ref", default=None)
    parser.add_argument("--amount", default=None)
    parser.add_argument("--url", default=os.getenv("API_URL", "http://localhost:8000"))
    parser.add_argument("--secret", default=os.getenv("WEBHOOK_SECRET", "whsec_dev"))
    args = parser.parse_args()

    payload = {
        "event_id": args.event_id or f"evt_{uuid.uuid4().hex[:16]}",
        "payment_ref": args.payment_ref or f"pay_ext_{uuid.uuid4().hex[:12]}",
        "booking_id": args.booking,
        "status": args.status,
    }
    if args.amount:
        payload["amount"] = args.amount

    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(args.secret.encode(), body, hashlib.sha256).hexdigest()

    r = httpx.post(
        f"{args.url}/payments/webhook/",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
    )
    print("sent:", json.dumps(payload))
    print(r.status_code, r.text)


if __name__ == "__main__":
    main()
