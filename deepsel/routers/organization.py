from deepsel.models.organization import OrganizationModel as Model
from deepsel.utils.crud_router import CRUDRouter
from deepsel.utils.generate_crud_schemas import generate_CRUD_schemas
from deepsel.utils.get_current_user import get_current_user
from fastapi import Depends

[ReadBase, CreateSchema, UpdateSchema, SearchSchema] = generate_CRUD_schemas(Model)

class ReadSchema(ReadBase):
    # internal settings values may be null for non-admin users
    mail_username: str = None
    mail_password: str = None
    mail_from: str = None
    mail_port: str = None
    mail_server: str = None
    mail_from_name: str = None
    mail_validate_certs: bool = None
    mail_use_credentials: bool = None
    mail_tls: bool = None
    mail_ssl: bool = None


router = CRUDRouter(
    read_schema=ReadSchema,
    search_schema=SearchSchema,
    create_schema=CreateSchema,
    update_schema=UpdateSchema,
    db_model=Model,
    dependencies=[Depends(get_current_user)],
    delete_one_route=False,
    search_route=False,
    create_route=False,
    export_route=False,
    import_route=False,
)
