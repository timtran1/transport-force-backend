from deepsel.utils.text_cases import pascal_to_snake, snake_to_camel, snake_to_pascal, snake_to_capitalized
from deepsel.utils.get_field_info import get_field_info
from sqlalchemy.ext.declarative import DeclarativeMeta
from pydantic import BaseModel as PydanticModel
from typing import Any

technical_relationships = [
    'organization',
]

class RelationshipInfo(PydanticModel):
    name: str
    camel_name: str
    pascal_name: str
    human_name: str
    type: str
    table_name: str
    class_name: str
    foreign_key_field: dict = None
    secondary: str = None
    back_populates: Any = None


class RelationshipInfoResult(PydanticModel):
    one2many: list[RelationshipInfo] = []
    many2many: list[RelationshipInfo] = []
    many2one: list[RelationshipInfo] = []


def get_relationships(cls: [DeclarativeMeta]) -> RelationshipInfoResult:
    result = {
        'one2many': [],
        'many2many': [],
        'many2one': [],
    }
    fields = {
        m.key: get_field_info(m).dict() for m in cls.__table__.columns
    }
    foreign_key_fields = [field for field in fields.values() if field['is_foreign_key']]
    foreign_key_models = [field['related_table'] for field in foreign_key_fields]

    for name, value in vars(cls).items():
        if name in technical_relationships:
            continue
        if hasattr(value, 'prop') and hasattr(value.prop, 'argument') and value.prop.argument:
            class_name = value.prop.argument
            # check if string type, otherwise it is a relatioship from backref which we dont support
            if type(class_name) != str:
                continue

            table_name = pascal_to_snake(class_name.replace('Model', ''))

            if value.prop._init_args.secondary.argument:
                # secondary table is defined, this is a many2many relationship
                result['many2many'].append({
                    "name": name,
                    "camel_name": snake_to_camel(name),
                    "pascal_name": snake_to_pascal(name),
                    "human_name": snake_to_capitalized(name),
                    "type": 'many2many',
                    "table_name": table_name,
                    "class_name": class_name,
                    "secondary": value.prop._init_args.secondary.argument,
                    "back_populates": value.prop.back_populates,
                })

            # check if there is a foreign key field with the same model name
            elif table_name in foreign_key_models:
                #  this is a many2one relationship
                result['many2one'].append({
                    "name": name,
                    "camel_name": snake_to_camel(name),
                    "pascal_name": snake_to_pascal(name),
                    "human_name": snake_to_capitalized(name),
                    "type": 'many2one',
                    "table_name": table_name,
                    "class_name": class_name,
                    "foreign_key_field":
                        [field for field in foreign_key_fields if field['related_table'] == table_name][0],
                })
            else:
                # most likely this is a one2many relationship
                result['one2many'].append({
                    "name": name,
                    "camel_name": snake_to_camel(name),
                    "pascal_name": snake_to_pascal(name),
                    "human_name": snake_to_capitalized(name),
                    "type": 'one2many',
                    "table_name": table_name,
                    "class_name": class_name,
                    "back_populates": value.prop.back_populates,
                })

    return RelationshipInfoResult(**result)
