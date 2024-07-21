from sqlalchemy import Boolean, Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from fastapi import HTTPException
from db import Base
from deepsel.mixins.address import AddressMixin
from deepsel.mixins.orm import ORMBaseMixin
from sqlalchemy.orm import Session
from deepsel.models.user import UserModel


class OrganizationModel(Base, ORMBaseMixin, AddressMixin):
    __tablename__ = "organization"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

    image_attachment_id = Column(Integer, ForeignKey("attachment.id"))
    image = relationship("AttachmentModel", foreign_keys=[image_attachment_id])

    # internal settings
    mail_username = Column(String)
    mail_password = Column(String)
    mail_from = Column(String)
    mail_port = Column(String)
    mail_server = Column(String)
    mail_from_name = Column(String)
    mail_validate_certs = Column(Boolean, nullable=False, default=False)
    mail_use_credentials = Column(Boolean, nullable=False, default=True)
    mail_ssl_tls = Column(Boolean, nullable=False, default=False)
    mail_starttls = Column(Boolean, nullable=False, default=False)

    # public settings
    access_token_expire_minutes = Column(Integer, default=1440)
    require_2fa_all_users = Column(Boolean, default=False)
    allow_public_signup = Column(Boolean, default=True)

    @classmethod
    def get_public_settings(cls, organization_id: int, db: Session):
        organization = db.query(cls).get(organization_id)
        if not organization:
            raise HTTPException(status_code=404, detail="Organization not found")

        return {
            "id": organization.id,
            "name": organization.name,
            "access_token_expire_minutes": organization.access_token_expire_minutes,
            "require_2fa_all_users": organization.require_2fa_all_users,
            "allow_public_signup": organization.allow_public_signup,
        }

    # dont let anyone other than admin and super_admin roles to get settings
    @classmethod
    def get_one(
            cls, db: Session, user: UserModel, item_id: int, *args, **kwargs
    ) -> "OrganizationModel":
        org = super().get_one(db, user, item_id, *args, **kwargs)
        user_roles = user.get_user_roles()
        is_admin = any([role.string_id in ["admin_role", "super_admin_role"] for role in user_roles])

        if is_admin:
            return org
        else:
            return org.get_public_settings(org.id, db)
