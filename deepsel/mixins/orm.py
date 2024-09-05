import csv
import enum
import logging
import traceback
from datetime import UTC, datetime
from io import StringIO
from typing import Any, Optional

from dateutil.parser import parse as parse_date
from fastapi import File, HTTPException, status
from fastapi_crudrouter.core.sqlalchemy import PAGINATION
from pydantic import BaseModel as PydanticModel
from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import Session, Query

from deepsel.utils.check_delete_cascade import (
    AffectedRecordResult,
    get_delete_cascade_records_recursively,
)
from deepsel.utils.generate_crud_schemas import _get_relationships_class_map
from deepsel.utils.get_field_info import FieldInfo
from deepsel.utils.get_relationships import get_one2many_parent_id, get_relationships
from deepsel.utils.models_pool import models_pool


logger = logging.getLogger(__name__)


class RelationshipRecordCollection(PydanticModel):
    relationship_name: str
    linked_records: list[dict[str, Any]] = []
    linked_model_class: Any


class Operator(str, enum.Enum):
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


class OrderDirection(str, enum.Enum):
    asc = "asc"
    desc = "desc"


class OrderByCriteria(PydanticModel):
    field: str
    direction: OrderDirection = "asc"


class PermissionScope(str, enum.Enum):
    none = "none"
    own = "own"
    org = "org"
    all = "*"


class PermissionAction(str, enum.Enum):
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


class BulkDeleteResponse(DeleteResponse):
    deleted_count: int = 0


class ORMBaseMixin(object):
    __mapper__ = None

    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()

    created_at = Column(DateTime, default=lambda x: datetime.now(UTC))
    updated_at = Column(
        DateTime,
        default=lambda x: datetime.now(UTC),
        onupdate=lambda x: datetime.now(UTC),
    )
    string_id = Column(String, unique=True)
    system = Column(Boolean, default=False)
    active = Column(Boolean, default=True)
    is_technical = Column(Boolean, default=False)

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

        if hasattr(self, "string_id") and self.string_id:
            return f"<{self.__class__.__name__.replace('Model', '')}: {identifier} (id {self.string_id})>"
        elif hasattr(self, "id"):
            return f"<{self.__class__.__name__.replace('Model', '')}: {identifier} (id {self.id})>"

        return f"<{self.__class__.__name__.replace('Model', '')}: {identifier}"

    def __str__(self):
        return self.__repr__()

    @classmethod
    def create(
        cls,
        db: Session,
        user,
        values: dict,
        commit: Optional[bool] = True,
        *args,
        **kwargs,
    ) -> "[ORMBaseMixin]":
        model = models_pool[cls.__tablename__]
        [allowed, scope] = model._check_has_permission(PermissionAction.create, user)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have permission to create this resource type: {model.__tablename__}",
            )

        # if model has owner_id, only allow users to assign ownership to themselves
        if hasattr(model, "owner_id"):
            values["owner_id"] = user.id

        # if model has organization_id, only allow users to assign organization to themselves
        # unless they have role super_admin_role
        if hasattr(model, "organization_id"):
            user_roles = user.get_user_roles()
            is_super = any(
                [role.string_id == "super_admin_role" for role in user_roles]
            )
            if not is_super or not values.get("organization_id"):
                values["organization_id"] = user.organization_id

        # for every value in the format of <table_name>/<string_id>, get the record instance
        for key, value in values.items():
            if isinstance(value, str) and value.count("/") == 1:
                table_name, string_id = value.split("/")
                RelatedModel = models_pool.get(table_name)
                if RelatedModel:
                    record = (
                        db.query(RelatedModel).filter_by(string_id=string_id).first()
                    )
                    if record:
                        values[key] = record.id
                    else:
                        logger.error(f"Error finding record with string_id: {value}")

        relationships = get_relationships(model)
        relationship_classes = _get_relationships_class_map(model)

        many2many_records_to_link: list[RelationshipRecordCollection] = []
        one2many_records_to_create: list[RelationshipRecordCollection] = []

        # pop many2many relationship lists from values
        for relationship in relationships.many2many:
            if relationship.name in values:
                linked_records = values.pop(relationship.name)
                if linked_records:
                    many2many_records_to_link.append(
                        RelationshipRecordCollection(
                            relationship_name=relationship.name,
                            linked_records=linked_records,
                            linked_model_class=relationship_classes[relationship.name],
                        )
                    )

        # set attr for one2many relationships
        for relationship in relationships.one2many:
            if relationship.name in values:
                linked_records = values.pop(relationship.name)
                if linked_records:
                    one2many_records_to_create.append(
                        RelationshipRecordCollection(
                            relationship_name=relationship.name,
                            linked_records=linked_records,
                            linked_model_class=relationship_classes[relationship.name],
                        )
                    )

        try:
            # check if field is defined in class, if not pop it
            to_pop = []
            for key, value in values.items():
                if not hasattr(model, key):
                    to_pop.append(key)
            for key in to_pop:
                values.pop(key)

            instance = model(**values)
            db.add(instance)

            # now link many2many records
            if many2many_records_to_link:
                for collection in many2many_records_to_link:
                    LinkedModel = collection.linked_model_class
                    ids = [record["id"] for record in collection.linked_records]
                    record_instances = (
                        db.query(LinkedModel).filter(LinkedModel.id.in_(ids)).all()
                    )
                    setattr(instance, collection.relationship_name, record_instances)

            if commit:
                db.commit()
                db.refresh(instance)

                # now create the one2many records
                # since now we have the instance id after commit
                if one2many_records_to_create:
                    for collection in one2many_records_to_create:
                        LinkedModel = collection.linked_model_class
                        parent_key_field = get_one2many_parent_id(
                            LinkedModel, model.__tablename__
                        )
                        if parent_key_field:
                            for record_values in collection.linked_records:
                                record_values[parent_key_field.name] = instance.id
                                record_instance = LinkedModel.create(
                                    db, user, record_values
                                )
                                db.add(record_instance)
                    db.commit()

            return instance
        # catch unique constraint violation
        except IntegrityError as e:
            db.rollback()
            message = str(e.orig)
            detail = message.split("DETAIL:  ")[1]
            logger.error(
                f"Error creating record: {detail}\nFull traceback: {traceback.format_exc()}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error creating record: {detail}",
            )
        # catch permissions error
        except HTTPException as e:
            db.rollback()
            raise e
        except Exception:
            db.rollback()
            logger.error(f"Error creating record: {traceback.format_exc()}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred!",
            )

    def update(
        self,
        db: Session,
        user,
        values: dict,
        commit: Optional[bool] = True,
        *args,
        **kwargs,
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
                detail=f"You do not have permission to update this resource type: {self.__tablename__}",
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

        try:
            relationships = get_relationships(self.get_class())
            relationship_classes = _get_relationships_class_map(self.get_class())

            many2many_records_to_update: list[RelationshipRecordCollection] = []
            one2many_records_to_update: list[RelationshipRecordCollection] = []

            # pop many2many relationship lists from values
            for relationship in relationships.many2many:
                if relationship.name in values:
                    linked_records = values.pop(relationship.name, None)
                    if linked_records == []:
                        # if just empty list, simply remove all many2many records in this relationship
                        setattr(self, relationship.name, [])
                    else:
                        # if not empty list, update the many2many records
                        many2many_records_to_update.append(
                            RelationshipRecordCollection(
                                relationship_name=relationship.name,
                                linked_records=linked_records,
                                linked_model_class=relationship_classes[
                                    relationship.name
                                ],
                            )
                        )

            # pop one2many relationship lists from values
            for relationship in relationships.one2many:
                if relationship.name in values:
                    values_to_update = values.pop(relationship.name)
                    if values_to_update is not None:
                        # update intended
                        # this can be a list of records, or an empty list that is meant to be set to empty
                        # if it is None, then that means the frontend did not pass this key
                        one2many_records_to_update.append(
                            RelationshipRecordCollection(
                                relationship_name=relationship.name,
                                linked_records=values_to_update,
                                linked_model_class=relationship_classes[
                                    relationship.name
                                ],
                            )
                        )

            # update all values
            for field, value in values.items():
                if hasattr(self, field):
                    setattr(self, field, value)

            # now update many2many records
            for collection in many2many_records_to_update:
                LinkedModel = collection.linked_model_class
                ids = [record["id"] for record in collection.linked_records]
                record_instances = (
                    db.query(LinkedModel).filter(LinkedModel.id.in_(ids)).all()
                )
                setattr(self, collection.relationship_name, record_instances)

            # now update one2many records
            for collection in one2many_records_to_update:
                LinkedModel = collection.linked_model_class
                parent_key_field: FieldInfo = get_one2many_parent_id(
                    LinkedModel, self.__tablename__
                )

                if parent_key_field:
                    existing_records = getattr(self, collection.relationship_name)

                    for record_values in collection.linked_records:
                        # add new records
                        if not record_values.get("id"):
                            record_values[parent_key_field.name] = self.id
                            record_instance = LinkedModel.create(
                                db, user, record_values
                            )
                            db.add(record_instance)
                        # update existing records
                        else:
                            record_id = record_values.get("id")
                            record_instance = db.query(LinkedModel).get(record_id)
                            record_instance.update(
                                db, user, record_values, commit=False
                            )

                    # delete or unlink records that are not in the new list
                    for existing_record in existing_records:
                        new_list_record_ids = [
                            record["id"]
                            for record in list(
                                filter(lambda x: x.get("id"), collection.linked_records)
                            )
                        ]
                        if existing_record.id not in new_list_record_ids:
                            parent_key_column: Column = getattr(
                                LinkedModel, parent_key_field.name
                            )
                            if parent_key_column.nullable:
                                # set null on the parent key field, unlink from parent
                                existing_record.update(
                                    db,
                                    user,
                                    {parent_key_field.name: None},
                                    commit=False,
                                )
                            else:
                                # delete record
                                db.delete(existing_record)

            if commit:
                db.commit()
                db.refresh(self)

            return self
        # catch unique constraint violation
        except IntegrityError as e:
            if commit:
                db.rollback()
            message = str(e.orig)
            detail = message.split("DETAIL:  ")[1]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error updating record: {detail}",
            )
        except Exception:
            if commit:
                db.rollback()
            logger.error(f"Error updating record: {traceback.format_exc()}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred!",
            )

    def delete(
        self,
        db: Session,
        user,
        force: Optional[bool] = False,
        commit: Optional[bool] = True,
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
            db, [self]
        )
        if (
            affected_records.to_delete.keys() or affected_records.to_set_null.keys()
        ) and not force:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This record has dependencies.",
            )

        try:
            # Delete affected records
            self._delete_affected_records(db, affected_records)

            db.delete(self)
            if commit:
                db.commit()
            return {"success": True}

        except IntegrityError as e:
            if commit:
                db.rollback()
            message = str(e.orig)
            detail = message.split("DETAIL:  ")[1]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error deleting record: {detail}",
            )
        except Exception:
            if commit:
                db.rollback()
            logger.error(f"Error deleting record: {traceback.format_exc()}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred!",
            )

    @classmethod
    def get_one(
        cls, db: Session, user, item_id: int, *args, **kwargs
    ) -> "[ORMBaseMixin]":
        [allowed, scope] = cls._check_has_permission(PermissionAction.read, user)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to read this resource type",
            )

        query = db.query(cls)

        # if highest scope is own, only allow users to read their own resources
        if scope == PermissionScope.own:
            # if model has owner_id, only allow users read their own resources
            if hasattr(cls, "owner_id"):
                query.filter_by(id=item_id, owner_id=user.id)
            # else if model is User, only allow users to read themselves
            elif cls.__tablename__ == "user":
                if item_id != user.id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have permission to read this resource",
                    )
            # else if model is Organization, only allow users to read their organization
            elif cls.__tablename__ == "organization":
                if item_id != user.organization_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have permission to read this resource",
                    )

        # if highest scope is org, only allow users to read resources in their organization
        elif scope == PermissionScope.org:
            # if model has organization_id, only allow users to read resources in their organization
            if hasattr(cls, "organization_id"):
                query.filter_by(id=item_id, organization_id=user.organization_id)
            # else if model is Organization, only allow users to read their organization
            elif cls.__tablename__ == "organization":
                if item_id != user.organization_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not have permission to read this resource",
                    )

        return db.query(cls).get(item_id)

    @classmethod
    def get_all(
        cls, db: Session, user, pagination: PAGINATION, *args, **kwargs
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
        user,
        pagination: PAGINATION,
        search: Optional[SearchQuery] = None,
        order_by: Optional[OrderByCriteria] = None,
        *args,
        **kwargs,
    ):
        model = models_pool[cls.__tablename__]
        [allowed, scope] = model._check_has_permission(PermissionAction.read, user)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to read this resource type",
            )

        skip, limit = pagination.get("skip"), pagination.get("limit")
        query = db.query(model)

        if search:
            query = cls._apply_search_conditions(query, search, model)

        if order_by:
            # check if field is in table
            if not hasattr(model, order_by.field):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f'Field "{order_by.field}" does not exist on this resource type',
                )

            if order_by.direction == "asc":
                query = query.order_by(getattr(model, order_by.field))
            elif order_by.direction == "desc":
                query = query.order_by(getattr(model, order_by.field).desc())

        # build query based on permission scope, paginate, and return
        query = cls._build_query_based_on_scope(query, user, scope, model)

        return {"total": query.count(), "data": query.offset(skip).limit(limit).all()}

    @classmethod
    def bulk_delete(
        cls,
        db: Session,
        user,
        search: SearchQuery,
        force: Optional[bool] = False,
        *args,
        **kwargs,
    ) -> BulkDeleteResponse:
        """
        Bulk delete with search query

        @param db: The database session.
        @param user: The user performing the action.
        @param search: The search query.
        @param force: Allow to delete referenced records
        @param args:
        @param kwargs:
        @return: BulkDeleteResponse
        """
        [allowed, scope] = cls._check_has_permission(PermissionAction.delete, user)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this resource type",
            )

        # Start a transaction
        try:
            # Get model
            model = models_pool[cls.__tablename__]

            # Get query
            query = db.query(cls)

            # apply search conditions to find deleting record
            query = cls._apply_search_conditions(query, search, model)

            # Build query based on permission scope, paginate, and return
            query = cls._build_query_based_on_scope(query, user, scope, model)

            # Get the records to be deleted
            records_to_delete = query.all()

            # Delete referenced/effected records if force param is True
            if force:
                # Get affected records
                affected_records: AffectedRecordResult = (
                    get_delete_cascade_records_recursively(
                        db, records=records_to_delete
                    )
                )

                # Delete affected records
                cls._delete_affected_records(db, affected_records)

            # Delete main records
            for record in records_to_delete:
                db.delete(record)
            db.commit()

            # Return the result
            return BulkDeleteResponse(
                success=True, deleted_count=len(records_to_delete)
            )

        except IntegrityError as e:
            db.rollback()
            message = str(e.orig)
            detail = message.split("DETAIL:  ")[1]
            logger.error(
                f"Error bulk deleting: {detail}\nFull traceback: {traceback.format_exc()}"
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete records because they are referenced by other records (or due to other integrity "
                "errors).",
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Error bulk deleting record: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred while deleting records: {str(e)}",
            )

    @classmethod
    def _delete_affected_records(
        cls, db: Session, affected_records: AffectedRecordResult
    ):
        """
        Delete referenced/affected records.

        @param db: The database session.
        @param affected_records: The affected records these will be deleted.
        @return: None
        """

        # Delete affected records
        for table, items in affected_records.to_delete.items():
            for item in items:
                db.delete(item.record)
        db.flush()

        # Set affected records to null
        for table, items in affected_records.to_set_null.items():
            for item in items:
                setattr(item.record, item.affected_field, None)
        db.flush()

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
        user,  # The user to check permissions for
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
        user,
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
        records = search_result["data"]
        csv_string = StringIO()
        model = models_pool[cls.__tablename__]

        if len(records) == 0:
            return csv_string

        # Convert the records to a list of dictionaries
        records = [rec.serialize() for rec in records]

        for record in records:
            record.pop("_sa_instance_state", None)

        column_names = [column.name for column in model.__table__.columns]
        csv_writer = csv.DictWriter(csv_string, fieldnames=column_names)
        csv_writer.writeheader()
        csv_writer.writerows(records)

        return csv_string

    @classmethod
    def import_records(cls, db: Session, user, csvfile: File, *args, **kwargs):
        contents = csvfile.file.read()
        buffer = StringIO(contents.decode("utf-8"))
        csv_reader = csv.DictReader(buffer)
        data: list[dict] = list(csv_reader)
        model = models_pool[cls.__tablename__]

        try:
            for row in data:
                row_data: dict = model._convert_csv_row(row)
                instance = None

                if row_data.get("id"):
                    instance = db.query(model).get(row_data.pop("id"))
                elif row_data.get("string_id"):
                    query = db.query(model).filter_by(
                        string_id=row_data.get("string_id")
                    )
                    if hasattr(model, "organization_id"):
                        query = query.filter_by(organization_id=user.organization_id)
                    instance = query.first()

                if instance:
                    instance.update(db, user, row_data, commit=False)
                else:
                    model.create(db, user, row_data, commit=False)

            db.commit()

        except IntegrityError as e:
            db.rollback()
            message = str(e.orig)
            detail = message.split("DETAIL:  ")[1]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error importing records: {detail}",
            )
        except ValueError as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid CSV field input: {e}",
            )
        except Exception:
            db.rollback()
            logger.error(
                f"Error importing record: \nFull traceback: {traceback.format_exc()}"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred!",
            )
        finally:
            buffer.close()
            csvfile.file.close()

        return {"success": True}

    def serialize(self) -> dict:
        result = self.__dict__.copy()
        # Convert Enum values to their actual string values
        # instead of the Enum object key
        for key, value in self.__dict__.items():
            if isinstance(value, enum.Enum):
                result[key] = value.value
        # Remove the SQLAlchemy internal state from the records
        result.pop("_sa_instance_state", None)
        return result

    @classmethod
    def _convert_csv_field_value(cls, value: Any, column: Column) -> Any:
        column_type = type(column.type)
        if value == "":
            return None
        elif column_type == Boolean:
            return value.lower() in ["true", "1", "t", "y", "yes"]
        elif column_type == Integer:
            return int(value)
        elif column_type == DateTime:
            return datetime.fromisoformat(value)
        elif column_type == Enum:
            return column.type.python_type(value)
        return value

    @classmethod
    def _convert_csv_row(cls, row: dict) -> dict:
        result = {}
        model = models_pool[cls.__tablename__]
        for column in model.__table__.columns:
            field_name = column.name
            if field_name in row and row[field_name] is not None:
                result[field_name] = model._convert_csv_field_value(
                    row[field_name], column
                )
        return result

    @classmethod
    def get_class(cls):
        return cls

    @classmethod
    def _apply_search_conditions(cls, query: Query, search: SearchQuery, model):
        """
        Apply search conditions to the query.
        Modify query object with the search conditions.

        @param query: The query object.
        @param search: The search query.
        @param db: The database session.
        @return The modified query object.
        """
        for logical_operator, conditions in search.model_dump().items():
            criteria_filters = []

            for condition in conditions:
                field, operator, value = (
                    condition["field"],
                    condition["operator"],
                    condition["value"],
                )

                ReferencedModel = model
                # check for case field is attr1.attr2
                is_relationship = "." in field

                if is_relationship:
                    fields = field.split(".")
                    if not hasattr(model, fields[0]):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f'Relation "{fields[0]}" does not exist on this resource type',
                        )
                    relation = getattr(model, fields[0])

                    # re-assign the ReferencedModel
                    ReferencedModel = models_pool[relation.property.target.name]
                    field = fields[1]
                    if not hasattr(ReferencedModel, fields[1]):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f'Field "{field}" does not exist on this resource type 1 ',
                        )

                elif not hasattr(ReferencedModel, field):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f'Field "{field}" does not exist on this resource type 2',
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

                # check if field is enum, if yes the value should be the enum value
                if field in ReferencedModel.__table__.columns:
                    column_type = ReferencedModel.__table__.columns[field].type
                    if column_type.__class__.__name__ == "Enum":
                        value = column_type.python_type(value)
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f'Field "{field}" does not exist on this resource type',
                    )

                condition_expr = None
                match operator:
                    case "=":
                        condition_expr = getattr(ReferencedModel, field) == value
                    case "!=":
                        condition_expr = getattr(ReferencedModel, field) != value
                    case "in":
                        if isinstance(value, list):
                            condition_expr = getattr(ReferencedModel, field).in_(value)
                    case ">":
                        condition_expr = getattr(ReferencedModel, field) > value
                    case ">=":
                        condition_expr = getattr(ReferencedModel, field) >= value
                    case "<":
                        condition_expr = getattr(ReferencedModel, field) < value
                    case "<=":
                        condition_expr = getattr(ReferencedModel, field) <= value
                    case "like":
                        condition_expr = getattr(ReferencedModel, field).like(
                            f"%{value}%"
                        )
                    case "ilike":
                        condition_expr = getattr(ReferencedModel, field).ilike(
                            f"%{value}%"
                        )
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

        return query

    @classmethod
    def _build_query_based_on_scope(
        cls, query: Query, user, scope: PermissionScope, model
    ) -> Query:
        """
        Build query based on permission scope and other conditions.

        @param query: The query object.
        @param user: The user performing the action.
        @param scope: The permission scope.
        @return: The modified query object.
        """
        if scope == PermissionScope.own:
            if hasattr(model, "owner_id"):
                query = query.filter_by(owner_id=user.id)
            elif model.__tablename__ == "user":
                query = query.filter_by(id=user.id)
        elif (
            scope == PermissionScope.org
            and hasattr(model, "organization_id")
            and user.organization_id is not None
        ):
            query = query.filter_by(organization_id=user.organization_id)
        return query
