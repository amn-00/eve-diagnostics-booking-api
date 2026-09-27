from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.deps import DB, CurrentUser
from app.errors import Conflict, Unauthorized
from app.models import User
from app.schemas import LoginIn, SignupIn, TokenOut, UserOut
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def signup(data: SignupIn, db: DB):
    if db.scalar(select(User.id).where(User.email == data.email)) is not None:
        raise Conflict("An account with this email already exists")

    user = User(email=data.email, full_name=data.full_name, password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two signups racing with the same email
        db.rollback()
        raise Conflict("An account with this email already exists")
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: DB):
    user = db.scalar(select(User).where(User.email == data.email))
    # same error either way so we don't reveal which emails are registered
    if user is None or not verify_password(data.password, user.password_hash):
        raise Unauthorized("Invalid email or password")

    return TokenOut(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_minutes * 60,
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user
