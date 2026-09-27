from fastapi import APIRouter, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.deps import DB, AdminUser, Pagination, paginate
from app.errors import Conflict, NotFound
from app.models import Centre, CentreTest, DiagnosticTest
from app.schemas import (
    CentreDetailOut,
    CentreIn,
    CentreOut,
    DiagnosticTestIn,
    DiagnosticTestOut,
    OfferingIn,
    OfferingOut,
    Page,
    PriceUpdateIn,
)

router = APIRouter(tags=["centres & tests"])


# ---- centres ----

@router.get("/centres/", response_model=Page[CentreOut])
def list_centres(
    db: DB,
    page: Pagination,
    city: str | None = Query(None, max_length=100),
    test_id: int | None = Query(None, gt=0, description="Only centres that offer this test"),
):
    query = select(Centre).order_by(Centre.id)
    if city:
        query = query.where(func.lower(Centre.city) == city.strip().lower())
    if test_id:
        query = query.join(CentreTest).where(CentreTest.test_id == test_id)
    return paginate(db, query, page)


@router.get("/centres/{centre_id}", response_model=CentreDetailOut)
def get_centre(centre_id: int, db: DB):
    centre = db.get(Centre, centre_id)
    if centre is None:
        raise NotFound("Centre not found")
    return centre


@router.post("/centres/", response_model=CentreOut, status_code=status.HTTP_201_CREATED)
def create_centre(data: CentreIn, db: DB, _: AdminUser):
    centre = Centre(**data.model_dump())
    db.add(centre)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("A centre with this name already exists in this city")
    db.refresh(centre)
    return centre


@router.post(
    "/centres/{centre_id}/tests",
    response_model=OfferingOut,
    status_code=status.HTTP_201_CREATED,
)
def add_test_to_centre(centre_id: int, data: OfferingIn, db: DB, _: AdminUser):
    if db.get(Centre, centre_id) is None:
        raise NotFound("Centre not found")
    if db.get(DiagnosticTest, data.test_id) is None:
        raise NotFound("Test not found")
    if db.get(CentreTest, (centre_id, data.test_id)) is not None:
        raise Conflict("This centre already offers this test, update the price instead")

    offering = CentreTest(centre_id=centre_id, test_id=data.test_id, price=data.price)
    db.add(offering)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("This centre already offers this test")
    db.refresh(offering)
    return offering


@router.patch("/centres/{centre_id}/tests/{test_id}", response_model=OfferingOut)
def update_test_price(centre_id: int, test_id: int, data: PriceUpdateIn, db: DB, _: AdminUser):
    offering = db.get(CentreTest, (centre_id, test_id))
    if offering is None:
        raise NotFound("This centre doesn't offer this test")
    # existing bookings keep the amount they were booked at
    offering.price = data.price
    db.commit()
    db.refresh(offering)
    return offering


# ---- tests ----

@router.get("/tests/", response_model=Page[DiagnosticTestOut])
def list_tests(db: DB, page: Pagination, q: str | None = Query(None, max_length=100)):
    query = select(DiagnosticTest).order_by(DiagnosticTest.id)
    if q:
        query = query.where(DiagnosticTest.name.ilike(f"%{q.strip()}%"))
    return paginate(db, query, page)


@router.post("/tests/", response_model=DiagnosticTestOut, status_code=status.HTTP_201_CREATED)
def create_test(data: DiagnosticTestIn, db: DB, _: AdminUser):
    test = DiagnosticTest(**data.model_dump())
    db.add(test)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("A test with this name already exists")
    db.refresh(test)
    return test
