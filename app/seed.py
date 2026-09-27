"""Adds an admin user and some sample centres/tests. Safe to run more than once.

    python -m app.seed
"""
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Centre, CentreTest, DiagnosticTest, User, UserRole
from app.security import hash_password

ADMIN_EMAIL = "admin@evehealth.dev"
ADMIN_PASSWORD = "admin12345"

TESTS = {
    "Complete Blood Count": "CBC - haemoglobin, WBC, platelets",
    "Lipid Profile": "Cholesterol, HDL, LDL, triglycerides",
    "Thyroid Profile (T3, T4, TSH)": None,
    "HbA1c": "Average blood sugar over ~3 months",
    "Chest X-Ray": None,
}

CENTRES = [
    ("Eve Diagnostics - Sector 62", "Noida", "A-12, Sector 62", {
        "Complete Blood Count": "349", "Lipid Profile": "599", "HbA1c": "450", "Chest X-Ray": "700",
    }),
    ("Eve Diagnostics - Saket", "Delhi", "M-4, Saket", {
        "Complete Blood Count": "399", "Thyroid Profile (T3, T4, TSH)": "650", "HbA1c": "499",
    }),
    ("Eve Diagnostics - Koramangala", "Bengaluru", "80 Feet Road, Koramangala", {
        "Complete Blood Count": "379", "Lipid Profile": "649", "Thyroid Profile (T3, T4, TSH)": "599",
    }),
]


def run() -> None:
    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.email == ADMIN_EMAIL)) is None:
            db.add(User(
                email=ADMIN_EMAIL,
                full_name="Eve Admin",
                password_hash=hash_password(ADMIN_PASSWORD),
                role=UserRole.ADMIN,
            ))

        tests = {}
        for name, description in TESTS.items():
            test = db.scalar(select(DiagnosticTest).where(DiagnosticTest.name == name))
            if test is None:
                test = DiagnosticTest(name=name, description=description)
                db.add(test)
            tests[name] = test
        db.flush()

        for name, city, address, prices in CENTRES:
            centre = db.scalar(select(Centre).where(Centre.name == name, Centre.city == city))
            if centre is None:
                centre = Centre(name=name, city=city, address=address)
                db.add(centre)
                db.flush()
            for test_name, price in prices.items():
                if db.get(CentreTest, (centre.id, tests[test_name].id)) is None:
                    db.add(CentreTest(centre_id=centre.id, test_id=tests[test_name].id, price=Decimal(price)))

        db.commit()
        print(f"Seed done. Admin login: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
