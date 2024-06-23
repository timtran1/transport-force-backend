import json
from typing import List

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, JSON
from sqlalchemy.orm import relationship

from db import Base, get_db
from deepsel.mixins.address import AddressMixin
from deepsel.mixins.orm import ORMBaseMixin
from deepsel.mixins.profile import ProfileMixin
from deepsel.models.notification import NotificationModel
from deepsel.models.role import RoleModel


class UserModel(Base, ORMBaseMixin, AddressMixin, ProfileMixin):
    __tablename__ = 'user'

    id = Column(Integer, primary_key=True)
    string_id = Column(String, unique=True)

    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)
    hashed_password = Column(String)
    signed_up = Column(Boolean, default=False)
    internal = Column(Boolean, default=False, nullable=False)
    device_info = Column(JSON)
    company_name = Column(String)

    roles = relationship('RoleModel', secondary='user_role')
    organization_id = Column(Integer, ForeignKey('organization.id'), nullable=True)
    organization = relationship('OrganizationModel')
    image_id = Column(Integer, ForeignKey('attachment.id'))
    image = relationship('AttachmentModel', foreign_keys=[image_id])
    cv_attachment_id = Column(Integer, ForeignKey('attachment.id'))
    cv = relationship('AttachmentModel', foreign_keys=[cv_attachment_id])

    is_use_2fa = Column(Boolean, default=False)
    secret_key_2fa = Column(String)
    recovery_codes = Column(JSON, nullable=True)

    location_logs = relationship('LocationLogModel', back_populates='owner')

    def is_public_user(self):
        return not self.signed_up or self.string_id == 'public_user'

    def _get_roles_recursively(self, role: [RoleModel], processed_roles: list[RoleModel] = None) -> set[RoleModel]:
        # Avoid circular references
        if processed_roles is None:
            processed_roles = set()

        if role in processed_roles:
            return set()

        processed_roles.add(role)

        roles = set()
        roles.add(role)

        for implied_role in role.implied_roles:
            roles.update(self._get_roles_recursively(implied_role, processed_roles))

        return roles

    def _get_permissions_recursively(self, role: [RoleModel], processed_roles: list[[RoleModel]] = None) -> set[str]:
        # Avoid circular references
        if processed_roles is None:
            processed_roles = set()

        if role in processed_roles:
            return set()

        processed_roles.add(role)

        permissions = set()
        if role.permissions:
            these_permissions = json.loads(role.permissions)
            for permission in these_permissions:
                permissions.add(permission)

        for implied_role in role.implied_roles:
            permissions.update(self._get_permissions_recursively(implied_role, processed_roles))

        return permissions

    def get_user_permissions(self, user: 'UserModel' = None) -> List[str]:
        user = user or self
        roles = user.roles
        permissions = set()  # Avoid duplicates

        for role in roles:
            permissions.update(self._get_permissions_recursively(role))

        return list(permissions)

    def get_user_roles(self, user: 'UserModel' = None) -> List[RoleModel]:
        user = user or self
        roles = user.roles
        all_roles = set()

        for role in roles:
            all_roles.update(self._get_roles_recursively(role))

        return list(all_roles)

    def notify(self, content: str, title: str = None, image: str = None, db=get_db()):
        notification = NotificationModel(
            title=title, content=content, image=image, owner_id=self.id
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        return notification
