from deepsel.models.email_template import EmailTemplateModel as Model
from deepsel.utils.crud_router import CRUDRouter
from deepsel.utils.generate_crud_schemas import generate_CRUD_schemas
from deepsel.utils.get_current_user import get_current_user
from fastapi import Depends

[ReadSchema, CreateSchema, UpdateSchema, SearchSchema] = generate_CRUD_schemas(Model)

router = CRUDRouter(
    read_schema=ReadSchema,
    search_schema=SearchSchema,
    create_schema=CreateSchema,
    update_schema=UpdateSchema,
    db_model=Model,
    dependencies=[Depends(get_current_user)]
)