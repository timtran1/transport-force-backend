from deepsel.models.role import RoleModel as Model
from deepsel.utils.crud_router import CRUDRouter
from deepsel.utils.generate_crud_schemas import generate_CRUD_schemas, generate_search_schema
from deepsel.utils.get_current_user import get_current_user
from fastapi import Depends

[ReadBaseSchema, CreateSchema, UpdateSchema, _] = generate_CRUD_schemas(Model)

class ReadSchema(ReadBaseSchema):
    implied_roles: list[ReadBaseSchema] = [] # This is skipped by the generator to avoid infinite recursion

SearchSchema = generate_search_schema(Model, ReadSchema)

router = CRUDRouter(
    read_schema=ReadSchema,
    search_schema=SearchSchema,
    create_schema=CreateSchema,
    update_schema=UpdateSchema,
    db_model=Model,
    dependencies=[Depends(get_current_user)]
)