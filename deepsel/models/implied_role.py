from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship
from deepsel.mixins.base_model import BaseModel
from db import Base


class ImpliedRoleModel(Base, BaseModel):
    __tablename__ = "implied_role"

    id = Column(Integer, primary_key=True)

    role_id = Column(Integer, ForeignKey("role.id"))
    implied_role_id = Column(Integer, ForeignKey("role.id"))