from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole
from app.security import decode_access_token

bearer = HTTPBearer(auto_error=False)

DB = Annotated[Session, Depends(get_db)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    db: DB,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if creds is None:
        raise _unauthorized("Not authenticated")

    user_id = decode_access_token(creds.credentials)
    if user_id is None:
        raise _unauthorized("Invalid or expired token")

    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized("User no longer exists")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


class PageParams:
    def __init__(
        self,
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        self.limit = limit
        self.offset = offset


Pagination = Annotated[PageParams, Depends()]


def paginate(db: Session, query: Select, page: PageParams) -> dict:
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.limit(page.limit).offset(page.offset)).all()
    return {"items": items, "total": total, "limit": page.limit, "offset": page.offset}
