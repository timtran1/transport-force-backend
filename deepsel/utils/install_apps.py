from settings import installed_apps
import importlib
import os
import csv
from fastapi import FastAPI
from deepsel.utils.models_pool import models_pool
from sqlalchemy.orm import Session
from sqlalchemy import update
from db import get_db
import logging
import json
from constants import DEFAULT_ORG_ID

logger = logging.getLogger(__name__)


def import_csv_data(
        file_name: str,
        db: Session,
        demo_data: bool = False,
        organization_id: int = DEFAULT_ORG_ID
):
    logger.debug(f'Importing {file_name}')
    # rm the .csv extension
    model_name = file_name.split('/')[-1][:-4]
    model = models_pool.get(model_name, None)
    if model:
        # import csv file
        with open(file_name, 'r', encoding='utf-8') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            # check if string_id column exists, if not throw error
            # except if we are inserting demo data
            if not demo_data and 'string_id' not in csv_reader.fieldnames:
                raise Exception(f'File {file_name} does not have required "string_id" column')

            owner_value_overwrite = None
            organization_value_overwrite = None

            # assign default values to owner_id and organization_id
            if hasattr(model, 'owner_id') and \
                    ('user/owner_id' not in csv_reader.fieldnames or 'owner_id' not in csv_reader.fieldnames):
                owner_value_overwrite = 'super_user'
            if hasattr(model, 'organization_id') and \
                    ('organization/organization_id' not in csv_reader.fieldnames or
                     'organization_id' not in csv_reader.fieldnames):
                organization_value_overwrite = str(organization_id)

            # convert to list of dicts
            csv_reader = list(csv_reader)

            # if overwrite is not None, we need to add the column to the csv_reader
            if owner_value_overwrite or organization_value_overwrite:
                for row in csv_reader:
                    if owner_value_overwrite:
                        row['user/owner_id'] = owner_value_overwrite
                    if organization_value_overwrite:
                        row['organization/organization_id'] = organization_value_overwrite

            # loop through rows
            for row in csv_reader:

                for key in list(row.keys()):
                    # pop all columns with format of <table_name>/<column_name>
                    # and replace them with <column_name>, after searching for provided string_id in the table
                    if '/' in key:
                        # means a string_id from another table
                        table_name, column_name = key.split('/')
                        # we need to remove the key anyway, this is not a real column name
                        value = row.pop(key)
                        # get model from table name
                        table_model = models_pool.get(table_name, None)
                        if table_model:
                            # get object from table
                            query = db.query(table_model).filter_by(string_id=value)
                            if hasattr(table_model, 'organization_id'):
                                query = query.filter_by(organization_id=organization_id)
                            obj = query.first()
                            if obj:
                                # add real column name with the record id
                                row[column_name] = getattr(obj, 'id')
                            else:
                                logger.error(f'Object {table_name} with string_id {value} not found for org {organization_id}')

                    # pop all columns with format of <source_type>:<field_name>
                    elif ':' in key:
                        source_type, field_name = key.split(':')
                        if source_type == 'file':
                            # the content of the column is the path to the file, and we need to read the content of the file
                            # and write it to the field_name
                            file_path = row.pop(key)
                            with open(file_path, 'r', encoding='utf-8') as file:
                                row[field_name] = file.read()
                                # check if field is JSON, if yes we load the json string
                                if hasattr(model, field_name) and str(getattr(model, field_name).type) == 'JSON':
                                    row[field_name] = json.loads(row[field_name])


                    # check if field is boolean, if yes convert it to boolean
                    elif row[key] == 'True' or row[key] == 'true':
                        row[key] = True
                    elif row[key] == 'False' or row[key] == 'false':
                        row[key] = False

                if not demo_data:
                    # check if object already exists
                    string_id = row['string_id']
                    query = db.query(model).filter_by(string_id=string_id)
                    if hasattr(model, 'organization_id'):
                        query = query.filter_by(organization_id=organization_id)
                    obj = query.first()
                    if obj:
                        # check if row has "system" equal to "true", if yes, then overwrite the object
                        if ('system' in row and row['system'] == True) or obj.system:
                            # update object
                            for key, value in row.items():
                                setattr(obj, key, value)
                            logger.debug(f'Updated {obj}')
                        # for site_content model, compare the content json keys, add any missing keys
                        # also remove any keys that are not in the csv
                        elif model_name == 'site_content':
                            existing_content = obj.content
                            for key, value in row['content'].items():
                                if key not in existing_content:
                                    existing_content[key] = value
                            for key in list(existing_content.keys()):
                                if key not in row['content']:
                                    existing_content.pop(key)
                            # json fields are not updated with setattr
                            db.execute(update(model).where(model.id == obj.id).values(content=existing_content))
                            logger.debug(f'Updated {obj}')
                    else:
                        # create object
                        obj = model(**row)
                        db.add(obj)
                        logger.debug(f'Added {obj}')

                else:
                    # demo data, we don't care if object exists or not
                    # create object regardless of existing object
                    obj = model(**row)
                    db.add(obj)
                    logger.debug(f'Added {obj}')

                db.commit()


def install_apps(fasptapi_app: FastAPI):
    app_folders = ['deepsel']
    app_folders += [f'apps/{app_name}' for app_name in installed_apps]

    # import routers for installed apps
    with next(get_db()) as db:
        for app_folder in app_folders:
            logger.info(f'Installing app {app_folder}...')
            # check if routers folder exists, if yes, import routers
            if os.path.isdir(f'{app_folder}/routers'):
                # list files in routers folder
                files = os.listdir(f'{app_folder}/routers')
                # filter files only python files, and not __init__.py
                files = list(filter(lambda x: x[-3:] == '.py' and x != '__init__.py', files))
                # loop through router files and import them
                for file in files:
                    module_name = f'{app_folder.replace("/", ".")}.routers.{file[:-3]}'
                    module = importlib.import_module(module_name)
                    fasptapi_app.include_router(module.router)
                    # print(f'Router {module_name} included')

            # check if data folder exists, if yes import data
            if os.path.isdir(f'{app_folder}/data'):
                module = importlib.import_module(f'{app_folder.replace("/", ".")}.data')
                import_order = getattr(module, 'import_order', [])

                for file in import_order:
                    import_csv_data(f'{app_folder}/data/{file}', db)
