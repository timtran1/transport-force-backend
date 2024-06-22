from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from deepsel.utils.install_apps import install_apps
from deepsel.utils.db_manager import startup_database_update
import logging
import os


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))


app = FastAPI(
    title='Deepsel Template API',
    description='© Deepsel Inc.',
    version='3.0',
    docs_url='/'
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

startup_database_update()
install_apps(app)