
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Float
from sqlalchemy.orm import relationship
from db import Base
from deepsel.mixins.base_model import BaseModel

class LocationLogModel(Base, BaseModel):
    __tablename__ = 'location_log'

    id = Column(Integer, primary_key=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    vehicle_id = Column(Integer, ForeignKey('vehicle.id'), nullable=False)
    vehicle = relationship('Vehicle', back_populates='locations')