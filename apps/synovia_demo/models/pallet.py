
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Text, func
from sqlalchemy.orm import relationship, Session
from db import Base
from deepsel.mixins.base_model import BaseModel
from deepsel.models.user import UserModel
from deepsel.models.attachment import AttachmentModel
from barcode import Code128
from deepsel.models.attachment import AttachmentTypeOptions
import os
from constants import DEFAULT_ORG_ID

class PalletModel(Base, BaseModel):
    __tablename__ = 'pallet'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    manifest = Column(Text)
    description = Column(Text)
    handling_notes = Column(Text)
    barcode_attachment_id = Column(Integer, ForeignKey('attachment.id'))

    barcode = relationship('AttachmentModel', foreign_keys=[barcode_attachment_id])
    scans = relationship('ScanModel')

    @classmethod
    def create(
            self, db: Session, user: UserModel, values: dict, *args, **kwargs
    ) -> "PalletModel":

        pallet = super().create(db, user, values, *args, **kwargs)

        # Create a barcode for the pallet
        barcode = Code128(f'pallet-{pallet.id}')

        # check if "files" directory exists, if not create it
        if not os.path.exists('files'):
            os.makedirs('files')

        barcode.save(f'files/pallet-{pallet.id}')
        attachment = AttachmentModel(
            name=f'pallet-{pallet.id}.svg',
            type=AttachmentTypeOptions.local,
            content_type='image/svg+xml',
            owner_id=user.id,
            organization_id=DEFAULT_ORG_ID
        )
        pallet.barcode = attachment
        pallet.barcode_attachment_id = attachment.id
        db.commit()

        return pallet