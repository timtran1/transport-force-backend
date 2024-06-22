import enum
import logging
import os
from enum import Enum
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import Column, Enum, Integer, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from constants import (
    FILESYSTEM,
    S3,
    S3_BUCKET,
    UPLOAD_SIZE_LIMIT,
    AZURE_STORAGE_CONTAINER,
    AZURE_STORAGE_CONNECTION_STRING
)
from db import Base
from deepsel.mixins.base_model import BaseModel
from deepsel.mixins.orm import DeleteResponse, PermissionAction
import random
import string
from azure.storage.blob import BlobServiceClient

logger = logging.getLogger(__name__)


def randomize_file_name(filename, length: int = 10):
    characters = string.ascii_letters + string.digits
    file_ext = os.path.splitext(filename)[1]
    file_name_part = os.path.splitext(filename)[0]
    random_string = ''.join(random.choice(characters) for _ in range(length))
    new_filename = f"{file_name_part}-{random_string}{file_ext}"

    return new_filename


class AttachmentTypeOptions(enum.Enum):
    s3 = "s3"
    azure = "azure"
    local = "local"
    external = "external"


class AttachmentModel(Base, BaseModel):
    __tablename__ = "attachment"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    type = Column(Enum(AttachmentTypeOptions))
    content_type = Column(String)
    local_directory = os.path.join("files")

    @classmethod
    def get_by_name(cls, db: Session, name: str):
        return db.query(cls).filter(cls.name == name).first()

    def create(self, db: Session, user: 'UserModel', file, *args, **kwargs) -> BaseModel:
        [allowed, scope] = self._check_has_permission(PermissionAction.create, user)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to create this resource type",
            )

        # if model has owner_id, only allow users to assign ownership to themselves
        if hasattr(self, "owner_id"):
            kwargs["owner_id"] = user.id

        # if model has organization_id, only allow users to assign organization to themselves
        if hasattr(self, "organization_id"):
            kwargs["organization_id"] = user.organization_id

        try:
            # Check file size limit
            file_size = file.size / 1024 / 1024
            if file_size > UPLOAD_SIZE_LIMIT:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File size limit of {UPLOAD_SIZE_LIMIT}MB exceeded",
                )
            # Generate a random string to append to the file name to avoid duplication
            new_filename = randomize_file_name(file.filename)
            file_extension = os.path.splitext(file.filename)[1].lower()
            content_type = self._guess_content_type(file_extension)
            kwargs.update({"content_type": content_type})

            # Save file based on FILESYSTEM environment variable
            if FILESYSTEM == "s3":
                s3_key = f"{new_filename}"
                S3.upload_fileobj(
                    file.file,
                    S3_BUCKET,
                    new_filename,
                    ExtraArgs={
                        "Metadata": {
                            "owner_id": str(user.id),
                            "model": self.__class__.__name__,
                            "field": "name",
                            "record_id": str(id),
                            "original_filename": file.filename,
                        }
                    },
                )

                kwargs["type"] = AttachmentTypeOptions.s3
                kwargs["name"] = s3_key

            elif FILESYSTEM == "azure":
                blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
                container_client = blob_service_client.get_container_client(AZURE_STORAGE_CONTAINER)
                blob_client = container_client.get_blob_client(new_filename)
                blob_client.upload_blob(file.file)
                kwargs["type"] = AttachmentTypeOptions.azure
                kwargs["name"] = new_filename

            else:
                # local storage
                os.makedirs(self.local_directory, exist_ok=True)
                local_path = os.path.join(self.local_directory, new_filename)
                with open(local_path, "wb") as f:
                    f.write(file.file.read())
                kwargs["type"] = AttachmentTypeOptions.local
                kwargs["name"] = new_filename
            for k, v in kwargs.items():
                setattr(self, k, v)
            db.add(self)
            db.commit()
            db.refresh(self)
            return self
        # catch unique constraint violation
        except IntegrityError as e:
            db.rollback()
            message = str(e.orig)
            detail = message.split("DETAIL:  ")[1]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error creating record: {detail}",
            )

    def delete(
            self,
            db: Session,
            user: "UserModel",
            force: Optional[bool] = False,
            *args,
            **kwargs,
    ) -> [DeleteResponse]:  # type: ignore
        response = super().delete(db=db, user=user, force=force, *args, **kwargs)
        if self.type == AttachmentTypeOptions.s3:
            try:
                S3.delete_object(Bucket=S3_BUCKET, Key=self.name)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to delete file from S3",
                )
        elif self.type == AttachmentTypeOptions.azure:
            try:
                blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
                container_client = blob_service_client.get_container_client(AZURE_STORAGE_CONTAINER)
                blob_client = container_client.get_blob_client(self.name)
                blob_client.delete_blob()
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to delete file from Azure Blob Storage",
                )
        elif self.type == AttachmentTypeOptions.local:
            try:
                local_path = os.path.join(self.local_directory, self.name)
                os.remove(local_path)
            except FileNotFoundError:
                logger.error(
                    f"Object Attachment with string_id {self.string_id} deleted with error: FileNotFoundError"
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to delete file from local storage",
                )
        return response

    @staticmethod
    def _guess_content_type(extension: str) -> str:
        # Define mapping of file extensions to content types
        content_types = {
            ".aac": "audio/aac",
            ".ai": "application/illustrator",
            ".avi": "video/x-msvideo",
            ".bmp": "image/bmp",
            ".bz2": "application/x-bzip2",
            ".css": "text/css",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".eps": "application/postscript",
            ".flac": "audio/flac",
            ".flv": "video/x-flv",
            ".gif": "image/gif",
            ".gz": "application/gzip",
            ".html": "text/html",
            ".ico": "image/vnd.microsoft.icon",
            ".ics": "text/calendar",
            ".indd": "application/x-indesign",
            ".jpeg": "image/jpeg",
            ".jpg": "image/jpeg",
            ".js": "application/javascript",
            ".json": "application/json",
            ".mkv": "video/x-matroska",
            ".mov": "video/quicktime",
            ".mp3": "audio/mpeg",
            ".mp4": "video/mp4",
            ".mpeg": "video/mpeg",
            ".mpg": "video/mpeg",
            ".mpga": "audio/mpeg",
            ".odp": "application/vnd.oasis.opendocument.presentation",
            ".ods": "application/vnd.oasis.opendocument.spreadsheet",
            ".odt": "application/vnd.oasis.opendocument.text",
            ".ogg": "audio/ogg",
            ".opus": "audio/opus",
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".ppt": "application/vnd.ms-powerpoint",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".psd": "image/vnd.adobe.photoshop",
            ".rar": "application/vnd.rar",
            ".rtf": "application/rtf",
            ".svg": "image/svg+xml",
            ".tar": "application/x-tar",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
            ".txt": "text/plain",
            ".wav": "audio/wav",
            ".webm": "video/webm",
            ".webp": "image/webp",
            ".wmv": "video/x-ms-wmv",
            ".xaml": "application/xaml+xml",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xml": "application/xml",
            ".xps": "application/vnd.ms-xpsdocument",
            ".zip": "application/zip",
            # Add more mappings as needed
        }
        return content_types.get(
            extension, "application/octet-stream"
        )  # Default to binary if extension not found
