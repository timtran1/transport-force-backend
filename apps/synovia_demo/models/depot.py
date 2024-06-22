
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, func
from sqlalchemy.orm import relationship
from db import Base
from deepsel.mixins.base_model import BaseModel

class DepotModel(Base, BaseModel):
    __tablename__ = 'depot'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    address = Column(String)