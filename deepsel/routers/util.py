from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session
from db import get_db
from deepsel.models.user import UserModel
from deepsel.models.organization import OrganizationModel
from deepsel.utils.get_current_user import get_current_user
from deepsel.utils.models_pool import models_pool
from db import engine
from deepsel.utils.check_delete_cascade import get_delete_cascade_records_recursively
from deepsel.utils.get_class_info import get_class_info

router = APIRouter(tags=["Utilities"], prefix="/util")
inspector = inspect(engine)


class DeleteCheckResponse(BaseModel):
    to_delete: dict[str, list[str]]
    to_set_null: dict[str, list[str]]


@router.get("/delete_check/{model}/{ids}", response_model=DeleteCheckResponse)
async def delete_check(
        model: str,  # table name
        ids: str,  # comma separated list of ids
        db: Session = Depends(get_db),
        user: UserModel = Depends(get_current_user),
):
    if model == "xray":
        model = "tracking_session"
    elif model == "xray_event":
        model = "tracking_event"

    ids = ids.split(',')

    Model = models_pool.get(model, None)
    if Model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

    records = db.query(Model).filter(Model.id.in_(ids)).all()
    if not records:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")

    affected_records = get_delete_cascade_records_recursively(db, records)

    return {
        'to_delete': {k: [str(row.record) for row in v] for k, v in affected_records.to_delete.items()},
        'to_set_null': {k: [str(row.record) for row in v] for k, v in affected_records.to_set_null.items()}
    }


class HealthResponse(BaseModel):
    status: str = 'ok'

@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok")


@router.get("/model_info/{model}", response_model=dict)
async def model_info(
        model: str,  # table name
        user: UserModel = Depends(get_current_user),
):
    # check if user has Admin or Super Admin role
    if not any(role.string_id in ['admin_role', 'super_admin_role'] for role in user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this information",
        )

    Model = models_pool.get(model, None)
    if Model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

    return get_class_info(Model)


@router.get('/public_settings/{organization_id}')
async def get_public_settings(organization_id: int, db: Session = Depends(get_db)):
    return OrganizationModel.get_public_settings(organization_id, db)
