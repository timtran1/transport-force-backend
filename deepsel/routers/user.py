import logging
from typing import Annotated, Any, List, Optional
import jwt
from fastapi import BackgroundTasks, Depends, HTTPException, Body, status
from sqlalchemy.orm import Session
import json

from constants import AUTH_ALGORITHM, RESET_PASSWORD_SECRET, RESET_PASSWORD_URL
from deepsel.models.role import RoleModel
from deepsel.models.user import UserModel as Model
from deepsel.models.email_template import EmailTemplateModel
from deepsel.utils import generate_recovery_codes
from deepsel.utils.crud_router import CALLABLE, CRUDRouter
from deepsel.utils.generate_crud_schemas import (
    generate_CRUD_schemas,
    generate_read_schema,
)
from deepsel.utils.get_current_user import get_current_user
from db import get_db
from pydantic import BaseModel
import pyotp 

logger = logging.getLogger(__name__)

[ReadSchema, CreateSchema, UpdateSchema, SearchSchema] = generate_CRUD_schemas(Model)
RoleReadSchema = generate_read_schema(RoleModel)


async def send_set_password_email(db: Session, organization_name: str, user: Model):
    token = jwt.encode(
        {"uid": user.id}, RESET_PASSWORD_SECRET, algorithm=AUTH_ALGORITHM
    )
    context={
        "name": user.name or user.username,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "action_url": RESET_PASSWORD_URL + "?t=" + token,
        "business_name": organization_name,
    }

    template = db.query(EmailTemplateModel).filter_by(string_id="setup_password_template").first()
    ok = await template.send(db, [user.email], context)
    logger.info(f"Password setup email sent to {user.email}")
    return ok

class UserCustomRouter(CRUDRouter):
    def _create(self, *args: Any, **kwargs: Any) -> CALLABLE:
        def route(
            model: self.create_schema,  # type: ignore
            background_tasks: BackgroundTasks,
            db: Session = Depends(self.db_func),
            user: Model = Depends(get_current_user),
        ) -> [Model]:
            new_user = self.db_model.create(db, user, model.dict())

            # send password setup email to new user
            organization_name = user.organization.name
            background_tasks.add_task(
                send_set_password_email, db, organization_name, new_user
            )

            return new_user

        return route


router = UserCustomRouter(
    read_schema=ReadSchema,
    search_schema=SearchSchema,
    create_schema=CreateSchema,
    update_schema=UpdateSchema,
    db_model=Model,
    dependencies=[Depends(get_current_user)],
)


class CurrentUser(ReadSchema):
    permissions: Optional[List[str]]
    all_roles: Optional[List[RoleReadSchema]]


@router.get("/util/me", response_model=CurrentUser)
def get_me(user: Model = Depends(get_current_user)):
    permissions = user.get_user_permissions()
    all_roles = (
        user.get_user_roles()
    )  # list of all explicitly assigned roles and implied roles, recursively

    current_user = CurrentUser(
        **ReadSchema.from_orm(user).dict(),  # return without password
        permissions=permissions,
        all_roles=all_roles,
    )
    return current_user



class Info2Fa(BaseModel):
    is_use_2fa: bool = False
    totp_uri: str = ""
    recovery_codes: list[str] = []

@router.put("/{id}/2fa-config")
def update_2fa_config(
    id: int,
    is_use_2fa: Annotated[bool, Body(embed=True)],
    confirmed: Annotated[bool, Body(embed=True)] = False,
    user: Model = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Info2Fa:
    user_to_update = db.query(Model).filter(Model.id == id).first()
    if not user_to_update:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    if confirmed:
        # in case confirm using 2fa. secret_key already generated before. no need to create secret_key again.
        if is_use_2fa:
            if not user_to_update.secret_key_2fa:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="secret_key_2fa not found")
            user_to_update.is_use_2fa = True
            # also generate recovery code for backup
            if not user_to_update.recovery_codes:
                recovery_codes = generate_recovery_codes()
                user_to_update.recovery_codes = json.dumps(recovery_codes)
        else:
            user_to_update.is_use_2fa = False
            user_to_update.secret_key_2fa = None
            user_to_update.recovery_codes = None
        db.commit()
        return Info2Fa(
            is_use_2fa=is_use_2fa, 
            recovery_codes=json.loads(user_to_update.recovery_codes) if is_use_2fa else [])
    
    # if not confirmed => only get secret_key (create if not exist) for showing QR
    if not user_to_update.secret_key_2fa:
        secret_key = pyotp.random_base32()
        user_to_update.secret_key_2fa = secret_key
        db.commit()
    totp_uri = pyotp.totp.TOTP(user_to_update.secret_key_2fa).provisioning_uri( 
        name=user_to_update.username, 
        issuer_name='Deepsel'
    )
    return Info2Fa(totp_uri = totp_uri)



@router.get("/{id}/2fa-config")
def get_2fa_uri(
    id: int,
    current_user: Model = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Info2Fa:
    user = db.query(Model).filter(Model.id == id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.is_use_2fa:
        totp_uri = pyotp.totp.TOTP(user.secret_key_2fa).provisioning_uri( 
            name=user.username, 
            issuer_name='Deepsel'
        )
        return Info2Fa(is_use_2fa=user.is_use_2fa, totp_uri=totp_uri)

    return Info2Fa()