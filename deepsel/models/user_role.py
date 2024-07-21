from sqlalchemy import Column, ForeignKey, Integer
from db import Base
from deepsel.mixins.orm import ORMBaseMixin


class UserRoleModel(Base, ORMBaseMixin):
    __tablename__ = 'user_role'

    user_id = Column(Integer, ForeignKey('user.id'), nullable=False, primary_key=True)
    role_id = Column(Integer, ForeignKey('role.id'), nullable=False, primary_key=True)