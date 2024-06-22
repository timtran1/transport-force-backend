from sqlalchemy import Column, Integer, String, Boolean
from db import Base
from deepsel.mixins.base_model import BaseModel

class NotificationModel(Base, BaseModel):
    __tablename__ = 'notification'

    id = Column(Integer, primary_key=True)
    title = Column(String)
    content = Column(String)
    link = Column(String)
    image = Column(String)
    read = Column(Boolean, default=False)