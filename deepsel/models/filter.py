from sqlalchemy import Column, Integer, String, Boolean, Enum
from db import Base
from deepsel.mixins.orm import ORMBaseMixin, Operator


class FilterModel(Base, ORMBaseMixin):
    __tablename__ = 'filter'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    model = Column(String, nullable=False)
    field = Column(String, nullable=False)
    operator = Column(Enum(Operator), nullable=False)
    value = Column(String)
    enabled = Column(Boolean, default=False)