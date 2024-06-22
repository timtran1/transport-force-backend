import json
import random
import string
from datetime import datetime, timedelta
from typing import Optional

import jwt
import pyotp
from fastapi import APIRouter, Body, Depends, Form, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing_extensions import Annotated

from constants import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    APP_SECRET,
    AUTH_ALGORITHM,
    DEFAULT_ORG_ID,
    RESET_PASSWORD_SECRET,
    RESET_PASSWORD_URL,
)
from db import get_db
from deepsel.models.organization import OrganizationModel
from deepsel.models.role import RoleModel, UserRoleModel
from deepsel.models.user import UserModel
from deepsel.routers.user import CurrentUser
from deepsel.utils import generate_recovery_codes
from deepsel.utils.get_current_user import credentials_exception, get_current_user
from deepsel.utils.generate_crud_schemas import generate_read_schema
from deepsel.routers.user import CurrentUser
from deepsel.models.email_template import EmailTemplateModel
import pyotp

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
router = APIRouter(tags=["Authentication"])
UserReadSchema = generate_read_schema(UserModel)


class UserInitSubmission(BaseModel):
    device_info: dict
    organization_id: int


class UserSignupSubmission(BaseModel):
    username: str
    password: str
    organization_id: int
    token: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    user: CurrentUser | None
    is_require_user_config_2fa: bool


class InitAnonymousUserResponse(BaseModel):
    token: str
    user: UserReadSchema


class SignupResponse(BaseModel):
    success: bool
    id: int


class ResetPasswordResponse(BaseModel):
    success: bool
    recovery_codes: list[str] = []


class ResetPasswordRequestSubmission(BaseModel):
    mixin_id: str  # email or username


class ResetPasswordSubmission(BaseModel):
    token: str
    new_password: str
    should_confirm_2fa_when_change_password: bool = False


class ChangePasswordSubmission(BaseModel):
    old_password: str
    new_password: str


async def email_reset_password(user: UserModel, db: Session):
    token = jwt.encode(
        {
            "uid": user.id,
            "exp": datetime.utcnow() + timedelta(hours=24),
        },
        RESET_PASSWORD_SECRET,
        algorithm=AUTH_ALGORITHM,
    )

    context = {
        "name": user.name or user.username,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "action_url": RESET_PASSWORD_URL + "?t=" + token,
        "business_name": "ICG",
    }

    template = db.query(EmailTemplateModel).filter_by(string_id="reset_password_template").first()
    ok = await template.send(db, [user.email], context)
    return ok


def authenticate_user(db, username: str, password: str) -> [UserModel]:
    user = (
        db.query(UserModel)
        .filter(UserModel.username == username)
        .filter(UserModel.active == True)
        .first()
    )
    if not user:
        return False
    if not pwd_context.verify(password, user.hashed_password):
        return False
    return user


@router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db),
    otp: Optional[str] = Form(None),
):
    user: UserModel = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # verify 2FA
    if user.is_use_2fa:
        totp = pyotp.TOTP(user.secret_key_2fa)
        if not totp.verify(otp):
            # check recovery codes if otp is invalid
            recovery_codes = json.loads(user.recovery_codes or "[]")
            if not recovery_codes or otp not in recovery_codes:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Incorrect OTP",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # remove recovery code after using
            if recovery_codes and otp in recovery_codes:
                recovery_codes.remove(otp)
                user.recovery_codes = (
                    json.dumps(recovery_codes) if len(recovery_codes) else None
                )
                db.commit()
    else:  # Require the user to configure 2FA if they haven't done so yet, but the organization forces 2FA.
        organization = db.query(OrganizationModel).get(user.organization_id)
        if organization.require_2fa_all_users:
            return {
                "access_token": "",
                "user": None,
                "is_require_user_config_2fa": True,
            }

    access_token_expire_minutes = ACCESS_TOKEN_EXPIRE_MINUTES
    if user.organization_id:
        organization = db.query(OrganizationModel).get(user.organization_id)
        if organization and organization.access_token_expire_minutes:
            access_token_expire_minutes = organization.access_token_expire_minutes

    access_token_expires = timedelta(minutes=access_token_expire_minutes)
    access_token = jwt.encode(
        {"uid": user.id, "exp": datetime.utcnow() + access_token_expires},
        APP_SECRET,
        algorithm=AUTH_ALGORITHM,
    )

    permissions = user.get_user_permissions()
    all_roles = user.get_user_roles()  # list of all explicitly assigned roles and implied roles, recursively
    current_user = CurrentUser(
        **UserReadSchema.model_validate(user, from_attributes=True).dict(),  # return without password
        permissions=permissions,
        all_roles=all_roles,
    )

    return TokenResponse(
        access_token=access_token,
        user=current_user,
        is_require_user_config_2fa=False
    )


@router.post("/signup", response_model=SignupResponse)
async def signup(user_data: UserSignupSubmission, db: Session = Depends(get_db)):
    # Check if the username already exists
    existing_user = (
        db.query(UserModel).filter(UserModel.username == user_data.username).first()
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists"
        )

    # Hash the password
    hashed_password = pwd_context.hash(user_data.password)

    if user_data.token:
        decoded_token = jwt.decode(
            user_data.token, APP_SECRET, algorithms=[AUTH_ALGORITHM]
        )
        owner_id = decoded_token["uid"]
        user = db.query(UserModel).get(owner_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
            )

        user.username = user_data.username
        user.hashed_password = hashed_password
        user.signed_up = True

    else:
        user = UserModel(
            username=user_data.username,
            hashed_password=hashed_password,
            organization_id=user_data.organization_id,
            signed_up=True,
        )
        db.add(user)

    db.commit()
    db.refresh(user)
    print(user.signed_up)

    # find role name "User" and assign to user
    role = db.query(RoleModel).filter(RoleModel.name == "User").first()
    if role:
        user.roles.append(role)
        db.commit()

    return {"success": True, "id": user.id}


@router.post("/init", response_model=InitAnonymousUserResponse)
async def create_anonymous_user(
    init_data: UserInitSubmission, db: Session = Depends(get_db)
):
    data = {
        "username": f'user_{"".join(random.choices(string.ascii_lowercase + string.digits, k=14))}',
        "hashed_password": pwd_context.hash(
            f'password_{"".join(random.choices(string.ascii_lowercase + string.digits, k=14))}'
        ),
        "email": f'email_{"".join(random.choices(string.ascii_lowercase + string.digits, k=14))}@gmail.com'
    }

    data.update(init_data)

    user = UserModel(**data)

    # find public role and assign to user
    role = (
        db.query(RoleModel)
        .filter(
            RoleModel.string_id == "public_role",
            RoleModel.organization_id == DEFAULT_ORG_ID,
        )
        .first()
    )
    if role:
        print(role.name)
        user.roles.append(role)

    db.add(user)
    db.commit()
    db.refresh(user)

    token = jwt.encode(
        {
            "uid": user.id,
        },
        APP_SECRET,
        algorithm=AUTH_ALGORITHM,
    )

    return {
        "token": token,
        "user": user,
    }


@router.post("/reset-password-request")
async def reset_password_request(
    input: ResetPasswordRequestSubmission, db: Session = Depends(get_db)
):
    # Check if the username/email already exists
    user = (
        db.query(UserModel)
        .filter(
            or_(UserModel.username == input.mixin_id, UserModel.email == input.mixin_id)
        )
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email/username does not exist",
        )
    user_email = user.email
    if not user_email:
        raise HTTPException(status_code=400, detail="User email is not configured")

    ok = await email_reset_password(user, db)
    if ok:
        return {"success": True}
    else:
        return {"success": False}


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(input: ResetPasswordSubmission, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(
            input.token, RESET_PASSWORD_SECRET, algorithms=[AUTH_ALGORITHM]
        )
        owner_id: str = payload.get("uid")
        if not owner_id:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    user: UserModel = db.query(UserModel).get(owner_id)
    if user is None:
        raise credentials_exception
    hashed_password = pwd_context.hash(input.new_password)
    user.hashed_password = hashed_password

    # in case the organization force 2fa leads to reset password, when submit new password => also confirm to use 2fa.
    # and after 2fa enabled, provide user recovery codes for backup
    if input.should_confirm_2fa_when_change_password:
        user.is_use_2fa = True
        if not user.recovery_codes:
            recovery_codes = generate_recovery_codes()
            user.recovery_codes = json.dumps(recovery_codes)
    db.commit()
    return {
        "success": True,
        "recovery_codes": (
            json.loads(user.recovery_codes or "[]") if user.is_use_2fa else []
        ),
    }


@router.post("/change-password")
def change_password(
    input: ChangePasswordSubmission,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    print(user.username)
    is_verified = pwd_context.verify(input.old_password, user.hashed_password)
    if not is_verified:
        raise HTTPException(status_code=400, detail="Invalid password")
    hashed_password = pwd_context.hash(input.new_password)
    user.hashed_password = hashed_password
    db.commit()
    return {"success": True}


class Info2FaDto(BaseModel):
    is_organization_require_2fa: bool = False
    is_already_config_2fa: bool = False
    totp_uri: str = ""


@router.post("/check-2fa-config")
async def check_2fa_config(
    token: Annotated[str, Body(embed=True)], db: Session = Depends(get_db)
) -> Info2FaDto:
    try:
        payload = jwt.decode(token, RESET_PASSWORD_SECRET, algorithms=[AUTH_ALGORITHM])
        owner_id: str = payload.get("uid")
        if not owner_id:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    user: UserModel = db.query(UserModel).get(owner_id)
    if user is None:
        raise credentials_exception

    is_organization_require_2fa = False
    if user.organization_id:
        organization = db.query(OrganizationModel).get(user.organization_id)
        is_organization_require_2fa = organization.require_2fa_all_users

    # If the user hasn't configured 2FA and the organization hasn't forced 2FA, then don't display the QR code
    if not user.is_use_2fa and not is_organization_require_2fa:
        return Info2FaDto(
            is_organization_require_2fa=False, is_already_config_2fa=False, totp_uri=""
        )

    if not user.secret_key_2fa:
        # create new secret key
        secret_key = pyotp.random_base32()
        user.secret_key_2fa = secret_key
        db.commit()

    totp_uri = pyotp.totp.TOTP(user.secret_key_2fa).provisioning_uri(
        name=user.username, issuer_name="Mini Tender"
    )
    return Info2FaDto(
        is_organization_require_2fa=is_organization_require_2fa,
        is_already_config_2fa=user.is_use_2fa,
        totp_uri=totp_uri,
    )