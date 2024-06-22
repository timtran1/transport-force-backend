from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWTError
from sqlalchemy.orm import Session

from constants import APP_SECRET, AUTH_ALGORITHM, DEFAULT_ORG_ID
from db import get_db
from deepsel.models.user import UserModel

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> [UserModel]:
    if token is None:
        # public user with string_id = 'publicuser'
        user = (
            db.query(UserModel)
            .filter(
                UserModel.string_id == "public_user",
                UserModel.organization_id == DEFAULT_ORG_ID,
            )
            .first()
        )
        if user is None:
            raise credentials_exception
        return user

    try:
        payload = jwt.decode(token, APP_SECRET, algorithms=[AUTH_ALGORITHM])
        owner_id: str = payload.get("uid")
        if not owner_id:
            raise credentials_exception
    except PyJWTError as e:
        raise credentials_exception

    user = db.query(UserModel).get(owner_id)
    if user is None:
        raise credentials_exception
    return user
