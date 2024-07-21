import enum
import inspect
import logging
from datetime import datetime, timedelta, UTC

from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Session

from db import Base
from deepsel.mixins.orm import ORMBaseMixin
from deepsel.utils.models_pool import models_pool

logger = logging.getLogger(__name__)


class UnitInterval(enum.Enum):
    minutes = "minutes"
    hours = "hours"
    days = "days"
    weeks = "weeks"
    # months and years are not supported by timedelta
    # and we don't need those edge cases for now


class CronModel(Base, ORMBaseMixin):
    __tablename__ = "cron"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)

    model = Column(String, nullable=False)
    method = Column(String, nullable=False)
    arguments = Column(String, default="[]")
    enabled = Column(Boolean, default=False)
    last_run = Column(DateTime)
    next_run = Column(DateTime, default=datetime.now())
    interval = Column(Integer, nullable=False, default=1)
    interval_unit = Column(
        Enum(UnitInterval), nullable=False, default=UnitInterval.days
    )

    async def execute(self, db: Session):
        self.last_run = datetime.now(UTC)

        model: [Base] = models_pool.get(self.model, None)
        method = getattr(model, self.method)
        is_async = inspect.iscoroutinefunction(method)
        arguments = eval(self.arguments)
        # add self and db to arguments
        arguments = [model, db] + arguments

        # run the method
        if is_async:
            result = await method(*arguments)
        else:
            result = method(*arguments)

        self.next_run = self.last_run + timedelta(**{self.interval_unit.value: self.interval})
        db.commit()
        db.refresh(self)

        return result

    def test_run(self, db: Session):
        logger.info(
            f"Executed successfully cron {self.name} with model {self.model} and method {self.method} with arguments {self.arguments}"
        )
