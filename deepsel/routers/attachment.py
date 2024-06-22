import os

from fastapi import Depends, File, Response, UploadFile, status, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from constants import (
    S3,
    S3_BUCKET,
    AZURE_STORAGE_CONNECTION_STRING,
    AZURE_STORAGE_CONTAINER,
    CLAMAV_HOST,
    S3_PRESIGN_EXPIRATION
)
from db import get_db
from deepsel.models.attachment import AttachmentModel as Model
from deepsel.models.attachment import AttachmentTypeOptions
from deepsel.models.user import UserModel
from deepsel.utils.crud_router import CRUDRouter
from deepsel.utils.generate_crud_schemas import generate_CRUD_schemas
from deepsel.utils.get_current_user import get_current_user
from clamd import ClamdNetworkSocket
from azure.storage.blob import generate_blob_sas, BlobSasPermissions, BlobServiceClient
from datetime import datetime, timedelta

[ReadSchema, CreateSchema, UpdateSchema, SearchSchema] = generate_CRUD_schemas(Model)

router = CRUDRouter(
    read_schema=ReadSchema,
    search_schema=SearchSchema,
    create_schema=CreateSchema,
    update_schema=UpdateSchema,
    db_model=Model,
    dependencies=[Depends(get_current_user)],
    create_route=False,
    update_route=False,
)


class UploadFileResponse(BaseModel):
    success: bool
    filename: str


@router.post("/", response_model=ReadSchema)
async def upload_file(
        file: UploadFile = File(...),
        user: UserModel = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    if CLAMAV_HOST:
        clamav = ClamdNetworkSocket(CLAMAV_HOST, 3310)
        scan_result = clamav.instream(file.file)
        file.file.seek(0)  # reset file pointer to the beginning
        ok = scan_result['stream'][0] == 'OK'
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File infected!"
            )

    instance = Model().create(db=db, user=user, file=file)
    return instance


@router.get("/serve/{file_name}")
def serve_file(
        file_name: str,
        response: Response,
        user: UserModel = Depends(get_current_user),
        db: Session = Depends(get_db),
):
    # Retrieve the file instance from the database
    instance = Model.get_by_name(
        db, file_name
    )  # Update with your actual method to retrieve the file instance
    if not instance:
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"detail": "File not found"}
    if instance.type == AttachmentTypeOptions.s3:
        # Redirect to the S3 pre-signed URL
        presigned_url = S3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": S3_BUCKET, "Key": instance.name},
            ExpiresIn=S3_PRESIGN_EXPIRATION.total_seconds(),
        )
        response.headers["Location"] = presigned_url
        response.status_code = status.HTTP_302_FOUND
        response.media_type = instance.content_type
        return response

    elif instance.type == AttachmentTypeOptions.azure:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        # Get the account key
        account_key = blob_service_client.credential.account_key
        account_name = blob_service_client.account_name
        # Generate the SAS token
        sas_token = generate_blob_sas(
            blob_name=file_name,
            account_name=account_name,
            account_key=account_key,
            container_name=AZURE_STORAGE_CONTAINER,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(minutes=30),
        )
        presigned_url = f"https://{account_name}.blob.core.windows.net/{AZURE_STORAGE_CONTAINER}/{file_name}?{sas_token}"
        response.headers["Location"] = presigned_url
        response.status_code = status.HTTP_302_FOUND
        response.media_type = instance.content_type
        return response
    elif instance.type == AttachmentTypeOptions.local:
        # Serve the file from the local disk
        try:
            local_path = os.path.join(Model.local_directory, instance.name)
            with open(local_path, "rb") as f:
                content = f.read()
            response.headers["Content-Type"] = instance.content_type
            return Response(content, media_type=instance.content_type)
        except FileNotFoundError:
            response.status_code = status.HTTP_404_NOT_FOUND
            return {"detail": "File not found"}
    else:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"detail": "Unsupported file type or storage mechanism"}
