
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, func
from deepsel.mixins.address import AddressMixin
from db import Base
from deepsel.mixins.base_model import BaseModel

class DepotModel(Base, BaseModel, AddressMixin):
    __tablename__ = 'depot'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)