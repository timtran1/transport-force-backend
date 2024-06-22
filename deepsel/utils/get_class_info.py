from deepsel.utils.get_field_info import get_field_info
from deepsel.utils.get_relationships import get_relationships
from deepsel.utils.technical_fields import technical_fields
from deepsel.utils.models_pool import models_pool
from sqlalchemy.ext.declarative import DeclarativeMeta


def get_class_info(
        cls: [DeclarativeMeta],
        processed_classes: dict = None,
        include_fields: bool = True,
        include_relationships: bool = True,
        parent_table_name: str = None
) -> dict:
    if processed_classes is None:
        processed_classes = {}

    class_name = cls.__name__
    if class_name in processed_classes:
        return processed_classes[class_name]
    processed_classes[class_name] = {}
    table_name = cls.__tablename__

    data = {'name': cls.__name__, }

    if include_fields:
        data['fields'] = {
            m.key: get_field_info(m).dict() for m in cls.__table__.columns if m.key not in technical_fields
        }
        # loop through foreign keys and add their class info
        for field in data['fields'].values():
            if field['is_foreign_key']:
                related_table = field['related_table']
                related_class = models_pool[related_table]
                related_class_info = get_class_info(related_class, processed_classes, include_fields=False)
                data['fields'][field['name']]['related_class_info'] = related_class_info

                # if the related class has one2many relationship with this class, mark this foreign key as parent id
                if related_class_info.get('relationships'):
                    if table_name in map(lambda x: x['table_name'], related_class_info['relationships']['one2many']):
                        data['fields'][field['name']]['is_parent_id'] = True

                # if parent_table_name matches the related table, mark this foreign key as parent id
                if parent_table_name == related_table:
                    data['fields'][field['name']]['is_parent_id'] = True

    if include_relationships:
        data['relationships'] = get_relationships(cls).dict()
        # loop through one2many relationships and add their class info
        for relationship in data['relationships']['one2many']:
            related_table = relationship['table_name']
            related_class = models_pool[related_table]
            related_class_info = get_class_info(
                related_class,
                processed_classes,
                include_relationships=False,
                parent_table_name=table_name
            )
            relationship['related_class_info'] = related_class_info

            # find the foreign key field that points to this class
            related_model_fields = related_class_info.get('fields')
            if related_model_fields:
                related_parent_id_field = next(
                    (k for k, v in related_model_fields.items() if v.get('is_parent_id')),
                    None
                )
                relationship['foreign_key_field'] = related_parent_id_field

    processed_classes.update({class_name: data})

    return data
