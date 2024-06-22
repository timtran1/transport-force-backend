
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Float, Enum, Text
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
    scan_type = Column(Enum(ScanType), nullable=False, default=ScanType.load)
    latitude = Column(Float)
    longitude = Column(Float)
    foo = Column(String)
    bar = Column(String)
    notes = Column(Text)

    pallet_id = Column(Integer, ForeignKey('pallet.id'), nullable=False)

    vehicle_id = Column(Integer, ForeignKey('vehicle.id'))
    vehicle = relationship('VehicleModel')
    depot_id = Column(Integer, ForeignKey('depot.id'))
    depot = relationship('DepotModel')