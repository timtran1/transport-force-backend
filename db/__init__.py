from constants import DATABASE_URL
from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.declarative import as_declarative
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.engine.base import Engine

engine: Engine = create_engine(DATABASE_URL)
SessionLocal: [Session] = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@as_declarative()
class Base:
    def _asdict(self):
        return {c.key: getattr(self, c.key) for c in inspect(self).mapper.column_attrs}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
