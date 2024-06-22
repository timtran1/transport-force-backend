import datetime
import os

import boto3
from dotenv import load_dotenv

load_dotenv()

# Database
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", 5432)
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# General settings
FILESYSTEM = os.getenv("FILESYSTEM", "local")
UPLOAD_SIZE_LIMIT = float(os.getenv("UPLOAD_SIZE_LIMIT", 5))  # unit: Megabyte
APP_SECRET = os.getenv("APP_SECRET", "your-secret-key")
RESET_PASSWORD_SECRET = os.getenv("RESET_PASSWORD_SECRET", "your-secret-key")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
RESET_PASSWORD_URL = os.getenv("RESET_PASSWORD_URL", FRONTEND_URL + "/reset-password")

# Optional
AUTH_ALGORITHM = os.getenv("AUTH_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24))

# ClamAV (Optional)
CLAMAV_HOST = os.getenv("CLAMAV_HOST", None)

# AWS S3 (Optional)
S3_BUCKET = os.getenv("S3_BUCKET")
S3_BACKUP_BUCKET = os.getenv("S3_BACKUP_BUCKET")
S3_PRESIGN_EXPIRATION = datetime.timedelta(
    minutes=int(os.getenv("S3_PRESIGN_EXPIRATION_MINUTES", 5))
)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
S3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)

# Azure Blob Storage (Optional)
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_STORAGE_KEY = os.getenv("AZURE_STORAGE_KEY")
AZURE_STORAGE_CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER")

DEFAULT_ORG_ID = 1