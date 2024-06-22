from sqlalchemy import text, Table
from deepsel.utils.models_pool import models_pool
from sqlalchemy import inspect
from db import engine, Base
from sqlalchemy.orm import Session
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy.ext.declarative import DeclarativeMeta as DBModel
from typing import Type


class AffectedRecord(PydanticBaseModel):
    display_name: str
    record: object
    affected_field:str


class AffectedRecordResult(PydanticBaseModel):
    to_delete: dict[str, list[AffectedRecord]]
    to_set_null: dict[str, list[AffectedRecord]]


def get_delete_cascade_records_recursively(
        db: Session,
        record: object,
        affected_records: dict = None
) -> AffectedRecordResult:
    if affected_records is None:
        affected_records = AffectedRecordResult(to_delete={}, to_set_null={})

    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    print(table_names)

    command = text(f"""
        SELECT DISTINCT
            conrelid::regclass AS table_name
        FROM
            pg_constraint AS con
        WHERE
            confrelid = '{record.__tablename__}'::regclass;
    """)
    tables_with_foreign_keys = db.execute(command)
    for row in tables_with_foreign_keys:
        table_name = row[0].replace('"', '')
        ReferringModel = models_pool.get(table_name, None)
        referring_foreign_key_constraints = [constraint for constraint in inspector.get_foreign_keys(table_name)
                                             if constraint['referred_table'] == record.__tablename__]
        referring_foreign_key_columns = [column for constraint in referring_foreign_key_constraints for column in
                                         constraint['constrained_columns']]
        # get list of not null columns
        referring_table = Table(table_name, Base.metadata, autoload_with=engine)
        not_null_columns = [column.name for column in referring_table.columns if not column.nullable]


        # get all records that refer to the record being deleted
        for column in referring_foreign_key_columns:
            records = db.query(ReferringModel).filter(getattr(ReferringModel, column) == record.id).all()
            record_results: list[AffectedRecord] = [
                AffectedRecord(
                    display_name=str(rec),
                    record=rec,
                    affected_field=column
                ) for rec in records
            ]

            if records:
                if column in not_null_columns:
                    # if the column is not nullable, we need to delete the records
                    if affected_records.to_delete.get(table_name):
                        affected_records.to_delete[table_name].extend(record_results)
                    else:
                        affected_records.to_delete[table_name] = record_results
                else:
                    # if the column is nullable, we need to set it to null
                    if affected_records.to_set_null.get(table_name):
                        affected_records.to_set_null[table_name].extend(record_results)
                    else:
                        affected_records.to_set_null[table_name] = record_results

            for item in record_results:
                get_delete_cascade_records_recursively(db, item.record, affected_records)

    return affected_records