
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Enum
from sqlalchemy.orm import relationship
from db import Base
from deepsel.mixins.base_model import BaseModel
import enum


class ScanType(enum.Enum):
    load = 'Load'
    off_depot = 'Off Depot'
    on_truck = 'On Truck'
    off_location = 'Off Location'


class ScanModel(Base, BaseModel):
    __tablename__ = 'scan'

    id = Column(Integer, primary_key=True)
    barcode = Column(String, nullable=False)
    scan_type = Column(Enum(ScanType), nullable=False)

    vehicle_id = Column(Integer, ForeignKey('vehicles.id'), nullable=True)
    depot_id = Column(Integer, ForeignKey('depots.id'), nullable=True)
    location_id = Column(Integer, ForeignKey('locations.id'), nullable=True)

    vehicle = relationship('Vehicle')
    depot = relationship('Depot')
    location = relationship('Location')
    user = relationship('User')