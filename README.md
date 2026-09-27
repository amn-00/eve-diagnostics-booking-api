# EVE Diagnostics Booking API

Backend for booking diagnostic tests at centres, with a mock payment flow and an idempotent payment webhook. Built for the EVE Healthcare SDE Intern assignment.

**Stack:** FastAPI, PostgreSQL, SQLAlchemy 2.0, Alembic, Pydantic v2, PyJWT, pytest, Docker.

## Running it

### With Docker (easiest)

```bash
docker compose up --build
docker compose exec api python -m app.seed    # optional: admin user + sample centres/tests
```

The API runs on http://localhost:8000 and Swagger docs are at http://localhost:8000/docs. Migrations run automatically when the container starts.

The seed script creates an admin account (`admin@evehealth.dev` / `admin12345`) and a few centres in Noida, Delhi and Bengaluru.

### Without Docker

You need Python 3.12 and a running Postgres.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then edit DATABASE_URL if needed
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload
```

### Tests

```bash
pytest
```

By default the tests use in-memory SQLite, so they don't need any setup. To run them against Postgres (which also runs the concurrent-webhook test):

```bash
TEST_DATABASE_URL=postgresql+psycopg://eve:eve@localhost:5432/eve_test pytest

# or inside docker (the eve_test db is created on first start)
docker compose run --rm -e TEST_DATABASE_URL=postgresql+psycopg://eve:eve@db:5432/eve_test api pytest
```

There are 66 tests. They cover auth, permissions, validation, the booking state machine, payments, idempotency keys, and the webhook edge cases.

## Project layout

```
app/
  main.py            app setup, request logging middleware
  config.py          settings from env vars
  database.py        engine + session
  models.py          SQLAlchemy models
  schemas.py         request/response models (validation lives here)
  security.py        bcrypt + JWT
  deps.py            auth dependencies, pagination
  errors.py          app exceptions -> HTTP status codes
  routers/           thin HTTP layer
  services/          booking + payment logic (state machine, webhook handling)
  seed.py            sample data
alembic/             migrations
scripts/send_webhook.py   pretends to be the payment provider
tests/
```

Routers only deal with HTTP. The actual rules (who can pay, which status changes are allowed, what a webhook does) live in `services/`, so they're easy to test and the same logic is shared between endpoints.

## API

All request/response bodies are JSON. Protected routes need `Authorization: Bearer <token>`. Money is returned as a string (`"499.00"`) so it doesn't go through floats.

| Method | Path | Auth | What it does |
|---|---|---|---|
| POST | `/auth/signup` | - | Create an account |
| POST | `/auth/login` | - | Get a JWT |
| GET | `/auth/me` | user | Current user |
| GET | `/centres/` | - | List centres (`?city=`, `?test_id=`, `?limit=`, `?offset=`) |
| GET | `/centres/{id}` | - | Centre with the tests it offers and their prices |
| POST | `/centres/` | admin | Create a centre |
| POST | `/centres/{id}/tests` | admin | Offer a test at a centre with a price |
| PATCH | `/centres/{id}/tests/{test_id}` | admin | Change the price |
| GET | `/tests/` | - | List tests (`?q=` to search) |
| POST | `/tests/` | admin | Create a test |
| POST | `/bookings/` | user | Book a test |
| GET | `/bookings/` | user | Your bookings (`?status=`, paginated). Admins see all |
| GET | `/bookings/{id}` | owner/admin | One booking |
| GET | `/bookings/{id}/payments` | owner/admin | Payment attempts for a booking |
| POST | `/bookings/{id}/cancel` | owner | Cancel |
| POST | `/payments/` | owner | Simulated payment |
| POST | `/payments/webhook/` | signature | Payment status update from the provider |
| GET | `/health` | - | Health check |

### Example flow

```bash
# sign up + log in
curl -X POST localhost:8000/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"aman@gmail.com","password":"password123","full_name":"Aman"}'

curl -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"aman@gmail.com","password":"password123"}'
# -> {"access_token":"eyJ...","token_type":"bearer","expires_in":3600}

TOKEN=eyJ...

# see what a centre offers
curl localhost:8000/centres/1

# book
curl -X POST localhost:8000/bookings/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"centre_id":1,"test_id":1,"appointment_at":"2026-10-05T10:30:00+05:30"}'
# -> {"id":1,"status":"PENDING","amount":"349.00", ...}

# pay (simulate is optional, leave it out for a random result)
curl -X POST localhost:8000/payments/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: 7f3c1a' \
  -d '{"booking_id":1,"simulate":"success"}'
# -> 201 {"payment":{"id":1,"status":"SUCCESS","provider_ref":"pay_...", ...},"booking_status":"CONFIRMED"}
# same request again with the same key -> 200 and the same payment, no second charge
```

### Webhook

```bash
python scripts/send_webhook.py --booking 2 --status SUCCESS --event-id evt_demo --payment-ref pay_demo
# 200 {"status":"processed","event_id":"evt_demo","outcome":"applied","booking_status":"CONFIRMED"}

python scripts/send_webhook.py --booking 2 --status SUCCESS --event-id evt_demo --payment-ref pay_demo
# 200 {"status":"duplicate","event_id":"evt_demo", ...}
```

Payload:

```json
{
  "event_id": "evt_123",
  "payment_ref": "pay_abc",
  "booking_id": 2,
  "status": "SUCCESS",
  "amount": "349.00"
}
```

`amount` is optional. If it's sent, it has to match the booking. The request must have an `X-Signature: sha256=<hex>` header, which is an HMAC-SHA256 of the raw body using `WEBHOOK_SECRET`. The script does this for you.

## Database design

```
users ──< bookings >── centre_tests >── centres
              │              │
              │              └──────── diagnostic_tests
              │
              ├──< payments
              └──< webhook_events
```

- **users**: email is unique and stored lowercased. `role` is USER or ADMIN.
- **centres**: `(name, city)` is unique, and city is indexed for filtering.
- **diagnostic_tests**: the test catalogue, with unique names.
- **centre_tests**: which centre offers which test, and at what price. The primary key is `(centre_id, test_id)`. Price is on this table and not on the test, because the same test costs different amounts at different centres. There's also a `CHECK (price > 0)`.
- **bookings**: user, centre, test, appointment time, amount and status. There's a composite foreign key `(centre_id, test_id) -> centre_tests`, so the database itself won't allow a booking for a test the centre doesn't offer. `amount` is copied from the price when the booking is made, so a later price change doesn't change old bookings.
- **payments**: one row per payment attempt. `provider_ref` (the provider's id for the payment) is unique, and `idempotency_key` is unique when present. `source` says whether it came from `POST /payments/` or from a webhook.
- **webhook_events**: every processed event, with a unique `event_id`, the raw payload, and an `outcome` (`applied`, `no_change`, `booking_not_pending`, `status_mismatch_ignored`). It works as an audit log, and it's what makes the webhook idempotent.

Postgres enums are used for statuses and roles. Migrations are in `alembic/versions`.

## Booking states

```
PENDING ──> CONFIRMED ──> CANCELLED
   │
   ├──────> FAILED
   └──────> CANCELLED
```

These are the only transitions allowed (`services/bookings.py`). FAILED and CANCELLED are final. If a payment fails, the user makes a new booking. A CONFIRMED booking can't go back to FAILED, so a late or out-of-order failure event can't undo a successful payment.

## How the payment and webhook parts work

**`POST /payments/`** locks the booking row (`SELECT ... FOR UPDATE`), checks that it belongs to the user and is still PENDING, and "calls the gateway". Here that's just a random result, or the forced `simulate` value. It then saves the payment and moves the booking to CONFIRMED or FAILED in the same transaction. Because of the row lock, two payment requests for the same booking can't both go through.

The optional `Idempotency-Key` header is for client retries. If a request with the same key comes in again, the original payment is returned with a 200 and nothing is charged again. Reusing a key for a different booking is rejected.

**`POST /payments/webhook/`**:

1. Verify the HMAC signature. Without this, anyone could confirm a booking for free.
2. Insert the `webhook_events` row **first**, in the same transaction as everything else. `event_id` is unique, so if the event was already processed the insert fails and we return `{"status": "duplicate"}` without touching anything. This also holds when two copies arrive at the same time: Postgres makes the second insert wait for the first transaction and then fail. There's a test that fires the same event from 5 threads at once and checks that exactly one gets applied.
3. Lock the booking. If it doesn't exist, return 404. Nothing is saved, so the provider can retry.
4. If we already have a payment with this `payment_ref` (for example the payment came through `POST /payments/`, or the provider re-sent it with a new event id), we don't create another one. If the status matches, it's a no-op. If it's different, it's logged and ignored, because payment results are treated as final.
5. Otherwise, save the payment and move the booking if the state machine allows it. A SUCCESS for a booking that is already cancelled or failed is still stored, and a warning is logged so it can be refunded.

Both endpoints use the same `_apply_to_booking` function, so they can't disagree about what a payment result means for a booking.

The webhook returns 200 for duplicates and for events that are valid but change nothing. That way a real provider stops retrying them. It returns 4xx only when the request itself is bad.

## Edge cases handled

| Case | Response |
|---|---|
| Invalid body / missing fields / bad email / short password | 422 |
| Duplicate signup (case-insensitive) | 409 |
| Wrong password or unknown email | 401 (same message for both) |
| Missing, malformed or expired JWT | 401 |
| Non-admin creating centres/tests | 403 |
| Booking a test the centre doesn't offer | 422 |
| Unknown centre/test/booking id | 404 |
| Appointment in the past, or without a timezone | 422 |
| Same user booking the same slot twice (also across timezones) | 409 |
| Viewing, paying or cancelling someone else's booking | 403 |
| Paying a booking that isn't PENDING | 409 |
| Cancelling an already cancelled/failed booking | 409 |
| Retried payment with same Idempotency-Key | 200, original payment |
| Same Idempotency-Key for a different booking | 422 |
| Duplicate webhook event (sequential or concurrent) | 200 `duplicate`, no changes |
| Webhook with bad/missing signature | 401 |
| Webhook for unknown booking | 404, not recorded |
| Webhook amount doesn't match the booking | 422 |
| Webhook `payment_ref` belongs to another booking | 422 |
| Late FAILED after CONFIRMED | ignored, booking stays CONFIRMED |
| SUCCESS for a cancelled booking | payment stored, booking unchanged, refund warning logged |

## Assumptions

- Signup always creates a normal USER. Admins are created with the seed script, or by changing the role in the database. I didn't want a public endpoint that hands out admin.
- There's no slot capacity or centre opening hours. Any future time can be booked. The only rule is that one user can't hold two active bookings for the same test, centre and time.
- `appointment_at` must include a timezone offset. It's stored in UTC and returned in UTC.
- One successful payment per booking. A failed payment makes the booking FAILED (terminal) instead of letting the user retry on the same booking. This keeps the state machine simple.
- `POST /payments/` acts like a gateway that responds synchronously. The webhook is the provider's async notification. In a real integration the webhook would be the source of truth, and `POST /payments/` would probably leave the booking PENDING until the webhook arrives.
- Only the patient can cancel a booking. Admins can view any booking but not cancel it.
- Cancelling a CONFIRMED booking is allowed. The refund itself is out of scope.

## Bonus items done

Docker + docker-compose, Swagger/OpenAPI (`/docs`), tests (SQLite + Postgres), structured JSON logging with a request id per request, pagination, webhook signature verification, and idempotency keys on payments. For webhook retries, the handler is safe to retry and returns a status code the provider can use to decide whether to retry.

## What I'd improve with more time

- Rate limiting on `/auth/login` and `/payments/`, using Redis in production.
- Moving webhook processing to a queue (Celery or similar). The endpoint would just store the event and return 200 quickly, a worker would process it, and failures would go to a dead-letter list.
- Refresh tokens and logout/token revocation.
- A real slot model: centre opening hours, capacity per slot, and preventing overbooking with a unique constraint or a counter.
- A proper refund flow instead of just logging a warning.
- Rejecting webhook events that are too old, by including a timestamp in the signature, to stop replay of very old signed requests.
- Caching the centre and test listings (they rarely change).
- Running CI on GitHub Actions with the Postgres test suite.
