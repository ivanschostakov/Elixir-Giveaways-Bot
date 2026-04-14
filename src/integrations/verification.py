import secrets
import ssl
import aiosmtplib
import certifi
from email.message import EmailMessage
from config import SMTP_USER, SMTP_PASSWORD

async def send_verification_code(email: str) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    msg = EmailMessage()
    msg["From"] = f"ElixirPeptide <{SMTP_USER}>"
    msg["To"] = email
    msg["Subject"] = "Код подтверждения"
    msg.set_content(
        f"""Здравствуйте!

Ваш код подтверждения: {code}

Если Вы не запрашивали код — сообщите об этом поддержке."""
    )

    await aiosmtplib.send(
        msg,
        hostname="smtp.gmail.com",
        port=587,
        start_tls=True,
        tls_context=ssl.create_default_context(cafile=certifi.where()),
        username=SMTP_USER,
        password=SMTP_PASSWORD,
        timeout=20,
    )

    return code
