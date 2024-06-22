from sqlalchemy import Column, Integer, String, Text
from db import Base
from deepsel.mixins.base_model import BaseModel
from deepsel.models.organization import OrganizationModel
from pydantic import EmailStr
from sqlalchemy.orm import Session, relationship
from jinja2 import Template
import logging
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig

logger = logging.getLogger(__name__)


class EmailTemplateModel(Base, BaseModel):
    __tablename__ = 'email_template'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    subject = Column(String, nullable=False, default='')
    content = Column(Text, nullable=False)

    async def send(
            self,
            db: Session,
            to: list[EmailStr],
            context: dict,
    ) -> bool:
        try:
            template = Template(self.content)
            rendered_template = template.render(**context)
            # also render the subject
            subject_template = Template(self.subject)
            rendered_subject = subject_template.render(**context)

            message = MessageSchema(
                subject=rendered_subject,
                recipients=to,
                body=rendered_template,
                subtype='html',
            )

            org = db.query(OrganizationModel).get(self.organization_id)
            conf = ConnectionConfig(
                MAIL_USERNAME=org.mail_username,
                MAIL_PASSWORD=org.mail_password,
                MAIL_FROM=org.mail_from,
                MAIL_FROM_NAME=org.mail_from_name,
                MAIL_PORT=org.mail_port,
                MAIL_SERVER=org.mail_server,
                MAIL_SSL_TLS=org.mail_ssl_tls,
                MAIL_STARTTLS=org.mail_starttls,
                USE_CREDENTIALS=org.mail_use_credentials,
                VALIDATE_CERTS=org.mail_validate_certs,
            )
            fm = FastMail(conf)
            await fm.send_message(message)
            logger.info(f"Email sent to {to}")
            return True
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False
