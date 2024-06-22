from deepsel.models.notification import NotificationModel
from deepsel.utils.generate_crud_schemas import generate_CRUD_schemas
from deepsel.utils.get_current_user import get_current_user
from deepsel.utils.crud_router import CRUDRouter
from fastapi import Depends
from db import get_db

[NotificationRead, NotificationCreate, NotificationUpdate, NotificationSearch] = generate_CRUD_schemas(NotificationModel)


router = CRUDRouter(
    read_schema=NotificationRead,
    search_schema=NotificationSearch,
    create_schema=NotificationCreate,
    update_schema=NotificationUpdate,
    
    db_model=NotificationModel,
    dependencies=[Depends(get_current_user)],
    delete_all_route=False,
)
