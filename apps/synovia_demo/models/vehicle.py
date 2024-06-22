from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, func
from sqlalchemy.orm import relationship
from db import Base
from deepsel.mixins.base_model import BaseModel


class VehicleModel(Base, BaseModel):
    __tablename__ = 'vehicle'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    license_plate = Column(String, unique=True, nullable=False)
    model = Column(String)
    make = Column(String)
    year = Column(Integer)
