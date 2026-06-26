from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)


async def send_email(to: str, subject: str, body: str) -> None:
    """Send an email over SMTP (async).

    If email_enabled=false, this is console mode: the email is logged, not sent.
    This lets you run the project without real SMTP. Port 587 uses STARTTLS
    (smtp_use_tls=true), which is the Gmail/Mailtrap standard.
    """
    if not settings.email_enabled:
        logger.info(
            "[EMAIL:console] (sending is off, EMAIL_ENABLED=false)\n"
            f"  To: {to}\n  Subject: {subject}\n  Body:\n{body}"
        )
        return

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        start_tls=settings.smtp_use_tls,
    )
    logger.info(f"Email sent | to={to} subject={subject!r}")
