import csv
import logging
from datetime import datetime, UTC
from enum import Enum
from io import StringIO
from typing import Any, Optional

from dateutil.parser import parse as parse_date
from fastapi import File, HTTPException, status
from fastapi_crudrouter.core.sqlalchemy import PAGINATION
from pydantic import BaseModel as PydanticModel
from sqlalchemy import Boolean, Column, DateTime, Integer, String, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import Session
from deepsel.utils.models_pool import models_pool

from deepsel.utils.check_delete_cascade import (
    AffectedRecordResult,
    get_delete_cascade_records_recursively,
)

logger = logging.getLogger(__name__)


class Operator(str, Enum):
    eq = "="
    ne = "!="
    in_ = "in"
    gt = ">"
    gte = ">="
    lt = "<"
    lte = "<="
    like = "like"
    ilike = "ilike"


class SearchCriteria(PydanticModel):
    field: str
    operator: Operator
    value: str | int | float | datetime | list[str | int | float | datetime] | Any


class SearchQuery(PydanticModel):
    AND: Optional[list[SearchCriteria]] = []
    OR: Optional[list[SearchCriteria]] = []


class OrderDirection(str, Enum):
    asc = "asc"
    desc = "desc"


class OrderByCriteria(PydanticModel):
    field: str
    direction: OrderDirection = "asc"


class PermissionScope(str, Enum):
    none = "none"
    own = "own"
    org = "org"
    all = "*"


class PermissionAction(str, Enum):
    read = "read"
    write = "write"
    delete = "delete"
    create = "create"
    all = "*"


# class SearchResponse(PydanticModel):
#     total: int
#     items: any


class DeleteResponse(PydanticModel):
    success: bool


class ORMBaseMixin(object):
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()

    created_at = Column(DateTime, default=lambda x: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda x: datetime.now(UTC), onupdate=lambda x: datetime.now(UTC))
    string_id = Column(String, unique=True)
    system = Column(Boolean, default=False)
    active = Column(Boolean, default=True)

    def __repr__(self):
        if hasattr(self, "name"):
            identifier = getattr(self, "name", None)
        elif hasattr(self, "display_name"):
            identifier = getattr(self, "display_name", None)
        elif hasattr(self, "title"):
            identifier = getattr(self, "title", None)
        elif hasattr(self, "username"):
            identifier = getattr(self, "username", None)
        elif hasattr(self, "email"):
            identifier = getattr(self, "email", None)
        else:
            identifier = ""

        return f"<{self.__class__.__name__.replace('Model', '')}:{identifier} (id {self.id})>"

    @classmethod
    def create(
            self, db: Session, user: "UserModel", values: dict, *args, **kwargs
    ) -> "[ORMBaseMixin]":
        [allowed, scope] = self._check_has_permission(PermissionAction.create, user)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to create this resource type",
            )

        # if model has owner_id, only allow users to assign ownership to themselves
        if hasattr(self, "owner_id"):
            values["owner_id"] = user.id

        # if model has organization_id, only allow users to assign organization to themselves
        if hasattr(self, "organization_id"):
            values["organization_id"] = user.organization_id

        # for every value in the format of <table_name>/<string_id>, get the record instance
        for key, value in values.items():
            if type(value) == str and "/" in value:
                try:
                    table_name, string_id = value.split("/")
                    model = models_pool.get(table_name)
                    if model:
                        record = db.query(model).filter_by(string_id=string_id).first()
                        if record:
                            values[key] = record.id
                except Exception as e:
                    logger.error(f"Error finding record with string_id: {e}")

        try:
            instance = self(**values)
            db.add(instance)
            db.commit()
            db.refresh(instance)
            return instance
        # catch unique constraint violation
        except IntegrityError as e:
            db.rollback()
            message = str(e.orig)
            detail = message.split("DETAIL:  ")[1]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error creating record: {detail}",
            )

    def update(
            self, db: Session, user: "UserModel", values: dict, *args, **kwargs
    ) -> "[ORMBaseMixin]":
        # check if system record
        if self.system:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System records cannot be modified.",
            )

        [allowed, scope] = self._check_has_permission(PermissionAction.write, user)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update this resource type",
            )

        # if highest scope is own, only allow users to update their own resources
        if scope == PermissionScope.own:
            # if model has owner_id, only allow users update their own resources
            if hasattr(self, "owner_id"):
                if self.owner_id != user.id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have permission to update this resource",
                    )
            # else if model is User, only allow users to update themselves
            elif self.__tablename__ == "user":
                if self.id != user.id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have permission to update this resource",
                    )

        # if highest scope is org, only allow users to update resources in their organization
        elif scope == PermissionScope.org:
            # if model has organization_id, only allow users to update resources in their organization
            if hasattr(self, "organization_id"):
                if self.organization_id != user.organization_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have permission to update this resource",
                    )

        for field, value in values.items():
            if hasattr(self, field):
                setattr(self, field, value)

        try:
            db.commit()
            db.refresh(self)
            return self
        # catch unique constraint violation
        except IntegrityError as e:
            db.rollback()
            message = str(e.orig)
            detail = message.split("DETAIL:  ")[1]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error updating record: {detail}",
            )

    def delete(
            self,
            db: Session,
            user: "UserModel",
            force: Optional[bool] = False,
            *args,
            **kwargs,
    ) -> [DeleteResponse]:
        # check if system record
        if self.system:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System records cannot be modified.",
            )

        [allowed, scope] = self._check_has_permission(PermissionAction.delete, user)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this resource type",
            )

        # if highest scope is own, only allow users to delete their own resources
        if scope == PermissionScope.own:
            # if model has owner_id, only allow users delete their own resources
            if hasattr(self, "owner_id"):
                if self.owner_id != user.id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have permission to delete this resource",
                    )
            # else if model is User, only allow users to delete themselves
            elif self.__tablename__ == "user":
                if self.id != user.id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have permission to delete this resource",
                    )

        # if highest scope is org, only allow users to delete resources in their organization
        elif scope == PermissionScope.org:
            # if model has organization_id, only allow users to delete resources in their organization
            if hasattr(self, "organization_id"):
                if self.organization_id != user.organization_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have permission to delete this resource",
                    )

        affected_records: AffectedRecordResult = get_delete_cascade_records_recursively(
            db, self
        )
        if (
                affected_records.to_delete.keys() or affected_records.to_set_null.keys()
        ) and not force:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This record has dependencies.",
            )

        try:
            # delete affected records
            for table, items in affected_records.to_delete.items():
                for item in items:
                    db.delete(item.record)

            # # set affected records to null
            for table, items in affected_records.to_set_null.items():
                for item in items:
                    setattr(item.record, item.affected_field, None)

            db.delete(self)
            db.commit()
            return {"success": True}

        except IntegrityError as e:
            db.rollback()
            message = str(e.orig)
            detail = message.split("DETAIL:  ")[1]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error deleting record: {detail}",
            )

    @classmethod
    def get_one(
            cls, db: Session, user: "UserModel", item_id: int, *args, **kwargs
    ) -> "[ORMBaseMixin]":
        [allowed, scope] = cls._check_has_permission(PermissionAction.read, user)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to read this resource type",
            )

        # if highest scope is own, only allow users to read their own resources
        if scope == PermissionScope.own:
            # if model has owner_id, only allow users read their own resources
            if hasattr(cls, "owner_id"):
                return (
                    db.query(cls)
                    .filter_by(
                        id=item_id,
                        owner_id=user.id
                    )
                    .first()
                )
            # else if model is User, only allow users to read themselves
            elif cls.__tablename__ == "user":
                if item_id != user.id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have permission to read this resource",
                    )

        # if highest scope is org, only allow users to read resources in their organization
        elif scope == PermissionScope.org:
            # if model has organization_id, only allow users to read resources in their organization
            if hasattr(cls, "organization_id"):
                return (
                    db.query(cls)
                    .filter_by(
                        id=item_id,
                        organization_id=user.organization_id
                    )
                ).first()

        return db.query(cls).get(item_id)

    @classmethod
    def get_all(
            cls, db: Session, user: "UserModel", pagination: PAGINATION, *args, **kwargs
    ) -> list["[ORMBaseMixin]"]:
        [allowed, scope] = cls._check_has_permission(PermissionAction.read, user)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to read this resource type",
            )

        skip, limit = pagination.get("skip"), pagination.get("limit")
        query = db.query(cls)

        # build query based on permission scope, paginate, and return
        if scope == PermissionScope.own:
            if hasattr(cls, "owner_id"):
                query = query.filter_by(owner_id=user.id)
            elif cls.__tablename__ == "user":
                query = query.filter_by(id=user.id)
        elif (
                scope == PermissionScope.org
                and hasattr(cls, "organization_id")
                and user.organization_id is not None
        ):
            query = query.filter_by(organization_id=user.organization_id)

        # filter by active=True
        query = query.filter_by(active=True)

        return query.offset(skip).limit(limit).all()

    @classmethod
    def search(
            cls,
            db: Session,
            user: "UserModel",
            pagination: PAGINATION,
            search: Optional[SearchQuery] = None,
            order_by: Optional[OrderByCriteria] = None,
            *args,
            **kwargs,
    ):
        [allowed, scope] = cls._check_has_permission(PermissionAction.read, user)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to read this resource type",
            )

        skip, limit = pagination.get("skip"), pagination.get("limit")
        query = db.query(cls)

        if search:
            for logical_operator, conditions in search.dict().items():
                criteria_filters = []

                for condition in conditions:
                    field, operator, value = (
                        condition["field"],
                        condition["operator"],
                        condition["value"],
                    )

                    model = cls
                    # check for case field is attr1.attr2
                    is_relationship = "." in field

                    if is_relationship:
                        fields = field.split(".")
                        if not hasattr(cls, fields[0]):
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f'Relation "{fields[0]}" does not exist on this resource type',
                            )
                        relation = getattr(cls, fields[0])

                        model = relation.property.mapper.class_
                        field = fields[1]
                        if not hasattr(relation.property.mapper.class_, fields[1]):
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f'Field "{field}" does not exist on this resource type',
                            )
                    elif not hasattr(cls, field):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f'Field "{field}" does not exist on this resource type',
                        )

                    datetime_fields = list(
                        filter(
                            lambda x: x.type.python_type == datetime,
                            model.__table__.columns,
                        )
                    )
                    is_datetime = field in [col.name for col in datetime_fields]

                    if is_datetime:
                        value = parse_date(value)

                    condition_expr = None
                    match operator:
                        case "=":
                            condition_expr = getattr(model, field) == value
                        case "!=":
                            condition_expr = getattr(model, field) != value
                        case "in":
                            if isinstance(value, list):
                                condition_expr = getattr(model, field).in_(value)
                        case ">":
                            condition_expr = getattr(model, field) > value
                        case ">=":
                            condition_expr = getattr(model, field) >= value
                        case "<":
                            condition_expr = getattr(model, field) < value
                        case "<=":
                            condition_expr = getattr(model, field) <= value
                        case "like":
                            condition_expr = getattr(model, field).like(f"%{value}%")
                        case "ilike":
                            condition_expr = getattr(model, field).ilike(f"%{value}%")
                        case _:
                            # Handle unsupported operators or other cases here
                            pass

                    if condition_expr is not None:
                        criteria_filters.append(condition_expr)
                        if is_relationship:
                            query = query.join(relation)

                if criteria_filters:
                    if logical_operator.lower() == "or":
                        query = query.filter(or_(*criteria_filters))
                    elif logical_operator.lower() == "and":
                        query = query.filter(and_(*criteria_filters))

                # check if any condition for "active" field, if not we filter by active=True
                if not any([condition["field"] == "active" for condition in conditions]):
                    query = query.filter_by(active=True)

        if order_by:
            # check if field is in table
            if not hasattr(cls, order_by.field):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f'Field "{order_by.field}" does not exist on this resource type',
                )

            if order_by.direction == "asc":
                query = query.order_by(getattr(cls, order_by.field))
            elif order_by.direction == "desc":
                query = query.order_by(getattr(cls, order_by.field).desc())

        # build query based on permission scope, paginate, and return
        if scope == PermissionScope.own:
            if hasattr(cls, "owner_id"):
                query = query.filter_by(owner_id=user.id)
            elif cls.__tablename__ == "user":
                query = query.filter_by(id=user.id)
        elif (
                scope == PermissionScope.org
                and hasattr(cls, "organization_id")
                and user.organization_id is not None
        ):
            query = query.filter_by(organization_id=user.organization_id)

        return {"total": query.count(), "data": query.offset(skip).limit(limit).all()}

    @classmethod
    def _filter_permission(cls, permission: str) -> bool:
        table = permission.split(":")[0]
        return table == cls.__tablename__

    @classmethod
    def _filter_action(cls, permission: str, action: PermissionAction) -> bool:
        allowed_action = permission.split(":")[1]
        return allowed_action == action or allowed_action == PermissionAction.all

    @classmethod
    def _check_has_permission(
            cls,
            action: PermissionAction,  # The action to check permissions for (e.g., 'read', 'write')
            user: "UserModel",  # The user to check permissions for
    ) -> [bool, PermissionScope]:
        """
        Check if the user has the required permissions for the given action.

        Args:
            action (str): The action to check permissions for (e.g., 'read', 'write', ').
            permissions (list[str]): List of permissions to check against.

        Returns:
            [bool, str]: A tuple containing a boolean indicating permission status and
            a string with the highest scope (e.g., 'own', 'org', '*').
        """
        all_permissions = user.get_user_permissions()

        # filter permissions by this table name or '*'
        table_permissions = list(filter(cls._filter_permission, all_permissions))
        if len(table_permissions) == 0:
            return False, PermissionScope.none

        # check if can do this action on table
        action_permissions = list(
            filter(lambda p: cls._filter_action(p, action), table_permissions)
        )
        if len(action_permissions) == 0:
            return False, PermissionScope.none

        # gather all scopes
        scopes = list(map(lambda x: x.split(":")[2], action_permissions))

        # get the highest scope, * > org > own
        highest_scope = PermissionScope.none
        for scope in scopes:
            if scope == PermissionScope.all:
                highest_scope = PermissionScope.all
                break
            elif scope == PermissionScope.org and highest_scope != PermissionScope.all:
                highest_scope = PermissionScope.org
            elif scope == PermissionScope.own and highest_scope == PermissionScope.none:
                highest_scope = PermissionScope.own

        return True, highest_scope

    @classmethod
    def export(
            cls,
            db: Session,
            user: "UserModel",
            pagination: PAGINATION,
            search: Optional[SearchQuery] = None,
            order_by: Optional[OrderByCriteria] = None,
            *args,
            **kwargs,
    ):
        search_result = cls.search(
            db=db,
            user=user,
            pagination=pagination,
            search=search,
            order_by=order_by,
            *args,
            **kwargs,
        )
        data = search_result["data"]
        csv_string = StringIO()
        if len(data) == 0:
            return csv_string
        fieldnames = list(data[0]._asdict().keys())
        csv_writer = csv.DictWriter(csv_string, fieldnames=fieldnames)
        csv_writer.writeheader()
        # Write each search result to the CSV file

        for item in data:
            csv_writer.writerow(item._asdict())
        return csv_string

    @classmethod
    def import_records(
            cls, db: Session, user: "UserModel", csvfile: File, *args, **kwargs
    ):
        [allowed_write, scope] = cls._check_has_permission(PermissionAction.write, user)
        [allowed_create, scope] = cls._check_has_permission(PermissionAction.create, user)
        if not allowed_write or not allowed_create:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to import this resource type",
            )

        contents = csvfile.file.read()
        buffer = StringIO(contents.decode("utf-8"))
        csv_reader = csv.DictReader(buffer)
        try:
            cls._create_or_update_bulk_objects(db, user, csv_reader)
        except Exception as e:
            logger.error("ORMBaseMixin:import_records failed. Error: %s", e.detail)
            raise e
        finally:
            buffer.close()
            csvfile.file.close()

        return {"success": True}

    @classmethod
    def _create_or_update_bulk_objects(cls, db: Session, user: "UserModel", data: csv.DictReader):
        header_keys = cls()._asdict().keys()
        header_csv = data.fieldnames

        # pop non existing fields
        for key in header_csv:
            if key not in header_keys:
                data.fieldnames.remove(key)

        to_update = []
        to_create = []

        for item in data:
            item = cls._convert_json_based_on_model(item)
            obj = None

            if item.get("id"):
                obj = db.query(cls).get(item["id"])
            elif item.get("string_id"):
                query = db.query(cls).filter_by(string_id=item["string_id"])
                if hasattr(cls, "organization_id"):
                    query = query.filter_by(organization_id=user.organization_id)
                obj = query.first()

            if obj:
                update_data = item.copy()
                update_data["id"] = obj.id
                update_data["string_id"] = obj.string_id
                to_update.append(update_data)
            else:
                to_create.append(item)

        try:
            if to_update:
                db.bulk_update_mappings(cls, to_update)
            if to_create:
                db.bulk_insert_mappings(cls, to_create)
            db.commit()
        except IntegrityError as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="IntegrityError: " + str(e),
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown error: " + str(e),
            )

    @classmethod
    def _convert_field(cls, value, column_type):
        if value == "" and column_type != String:
            return None
        elif column_type == Boolean:
            return value.lower() in ["true", "1", "t", "y", "yes"]
        elif column_type == Integer:
            return int(value)
        elif column_type == DateTime:
            return datetime.fromisoformat(value)
        return value

    @classmethod
    def _convert_json_based_on_model(cls, data):
        for column in cls.__table__.columns:
            field_name = column.name
            if field_name in data and data[field_name] is not None:
                column_type = type(column.type)
                data[field_name] = cls._convert_field(data[field_name], column_type)
        return data
