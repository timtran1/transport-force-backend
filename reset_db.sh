#!/bin/bash


# close all running containers
docker-compose down

# remove db container
docker rm -f deepsel-db

# remove all volumes
docker volume rm deepsel-python-template_pg_data -f

# up db container
docker-compose -f deepsel-local-docker-compose.yml up -d deepsel-db

# wait for db to be ready
#sleep 5

## wipe all migrations
#rm -rf ./alembic/versions/*.py
#
## init tables
#alembic revision --autogenerate -m "init"
#alembic upgrade head

## create data inserts with name of the file
#alembic revision --autogenerate -m "add user org role"
#file_name=$(ls ./alembic/versions/ | grep "add_user_org_role")
## append template data insert func to the file
#cat ./alembic/data_insert_templates/add_user_org_role.py >> ./alembic/versions/$file_name
#alembic upgrade head
#
#
#alembic revision --autogenerate -m "add cms data"
#file_name=$(ls ./alembic/versions/ | grep "add_cms_data")
#cat ./alembic/data_insert_templates/add_cms_data.py >> ./alembic/versions/$file_name
#alembic upgrade head