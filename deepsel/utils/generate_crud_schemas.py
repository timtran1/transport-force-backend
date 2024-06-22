import random
import string
from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel as PydanticModel
from pydantic import create_model, ConfigDict

from db import Base as DBModel
from deepsel.utils.get_relationships import get_relationships


def random_string() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=16))


def generate_create_schema(model: [DBModel]) -> [PydanticModel]:
    schema_name = model.__name__.replace("Model", "Create") + "-" + random_string()
    # exclude technical fields
    fields = _get_fields(
        model,
        [
            "id",
            "owner_id",
            "created_at",
            "updated_at",
            "organization_id",
            "hashed_password",
            "secret_key_2fa",
            "recovery_codes",
        ],
    )
    return create_model(schema_name, **fields)


def generate_read_schema(
    model: [DBModel], model_names_tree: [str] = []
) -> [PydanticModel]:
    # we need unique name for each schema model, if we have multiple read schemas for the same model
    # fastapi will throw error about duplicate models
    schema_name = model.__name__.replace("Model", "Read") + "-" + random_string()
    # exclude technical fields
    fields = _get_fields(model, ["hashed_password", "secret_key_2fa", "recovery_codes"])

    # we need to prevent infinite recursion
    # by recording the model names we have already visited
    # and not expanding them again
    new_tree = model_names_tree.copy()
    if model.__name__ not in model_names_tree:
        new_tree += [model.__name__]

    relationships_info = get_relationships(model).dict()
    relationships_class_map = _get_relationships_class_map(model)

    for rel in relationships_info["many2one"]:
        if rel["class_name"] in new_tree:
            # model exists in the tree, we need to prevent infinite recursion
            # do not expand this particular relationship
            continue
        new_tree += [model.__name__]

        read_schema = generate_read_schema(
            relationships_class_map[rel["name"]], new_tree
        )
        fields[rel["name"]] = (Optional[read_schema], None)

    for rel in relationships_info["one2many"]:
        if rel["class_name"] in new_tree:
            # model exists in the tree, we need to prevent infinite recursion
            # do not expand this particular relationship
            continue
        new_tree += [model.__name__]

        read_schema = generate_read_schema(
            relationships_class_map[rel["name"]], new_tree
        )
        fields[rel["name"]] = (Optional[list[read_schema]], None)

    for rel in relationships_info["many2many"]:
        if rel["class_name"] in new_tree:
            # model exists in the tree, we need to prevent infinite recursion
            # do not expand this particular relationship
            continue
        new_tree += [model.__name__]

        read_schema = generate_read_schema(
            relationships_class_map[rel["name"]], new_tree
        )
        fields[rel["name"]] = (Optional[list[read_schema]], None)

    return create_model(schema_name, **fields, __config__=ConfigDict(from_attributes=True))


def generate_search_schema(
    model: [DBModel], read_schema: [PydanticModel] = None
) -> [PydanticModel]:
    schema_name = model.__name__.replace("Model", "Search") + "-" + random_string()
    if not read_schema:
        read_schema = generate_read_schema(model)

    schema = create_model(schema_name, total=(int, ...), data=(list[read_schema], ...), __config__=ConfigDict(from_attributes=True))
    return schema


def generate_update_schema(model: [DBModel]) -> [PydanticModel]:
    schema_name = model.__name__.replace("Model", "Update") + "-" + random_string()
    # exclude id and owner_id
    fields = _get_fields(
        model,
        [
            "id",
            "owner_id",
            "created_at",
            "updated_at",
            "organization_id",
            "hashed_password",
            "secret_key_2fa",
            "recovery_codes",
        ],
    )
    return create_model(schema_name, **fields)


def _get_fields(model: DBModel, exclude: [str] = None) -> dict:
    fields = {}

    for column in model.__table__.columns:
        if exclude and column.name in exclude:
            continue

        col_type = column.type.python_type
        is_foreign_key = column.foreign_keys
        if is_foreign_key:
            # can be UUID, int or string (so we can pass string_id)
            col_type = Union[UUID, int, str]

        if column.nullable:
            col_type = Optional[col_type]
            default = None
        else:
            default = ...

        # json type can be both object and list
        if col_type == dict:
            col_type = Union[dict, list]

        fields[column.name] = (col_type, default)

    return fields


def _get_relationships_class_map(model: DBModel) -> dict:
    relationships = {}

    for relationship in model.__mapper__.relationships:
        relationships[relationship.key] = relationship.mapper.class_

    return relationships


def generate_CRUD_schemas(
    model: [DBModel],
) -> tuple[PydanticModel, PydanticModel, PydanticModel, PydanticModel]:
    create_schema = generate_create_schema(model)
    read_schema = generate_read_schema(model)
    update_schema = generate_update_schema(model)
    search_schema = generate_search_schema(model, read_schema)

    return read_schema, create_schema, update_schema, search_schema
