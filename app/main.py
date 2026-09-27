import logging
import time
import uuid

from fastapi import FastAPI, Request

from app.config import settings
from app.errors import AppError, app_error_handler
from app.logging_config import setup_logging
from app.routers import auth, bookings, centres, payments

setup_logging(settings.log_level)
log = logging.getLogger("app.requests")

app = FastAPI(
    title="EVE Healthcare - Diagnostic Bookings API",
    version="1.0.0",
    description="Diagnostic test bookings with simulated payments and an idempotent payment webhook.",
)
app.add_exception_handler(AppError, app_error_handler)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    log.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - start) * 1000, 1),
        },
    )
    return response


app.include_router(auth.router)
app.include_router(centres.router)
app.include_router(bookings.router)
app.include_router(payments.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
