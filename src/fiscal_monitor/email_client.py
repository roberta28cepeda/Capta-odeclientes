"""Cliente SMTP simples pra alertas por e-mail — alternativa/complemento
ao WhatsApp, pra escritório que não quer (ou não pode) receber alerta
fiscal por WhatsApp.

Usa `smtplib` da stdlib, sem serviço de e-mail transacional terceirizado
— funciona com qualquer provedor SMTP (Gmail, Zoho, SES, etc.) desde que
as credenciais sejam configuradas via variável de ambiente.
"""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class EmailError(RuntimeError):
    """Erro ao enviar e-mail via SMTP (conexão, autenticação, envio)."""


def send_email(
    to: str,
    subject: str,
    body: str,
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    smtp_from: str | None = None,
) -> None:
    remetente = smtp_from or smtp_username
    msg = MIMEMultipart()
    msg["From"] = remetente
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(remetente, [to], msg.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailError(f"Falha ao enviar e-mail pra {to}: {exc}") from exc
