import email
from unittest.mock import MagicMock, patch

import pytest

from src.fiscal_monitor.email_client import EmailError, send_email


def test_send_email_uses_starttls_login_and_sendmail():
    server = MagicMock()
    with patch("smtplib.SMTP") as mock_smtp:
        mock_smtp.return_value.__enter__.return_value = server
        send_email(
            "cliente@exemplo.com",
            "Assunto do alerta",
            "Corpo do e-mail",
            "smtp.exemplo.com",
            587,
            "usuario",
            "senha",
            smtp_from="alertas@leactis.com.br",
        )

    mock_smtp.assert_called_once_with("smtp.exemplo.com", 587, timeout=10)
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("usuario", "senha")
    server.sendmail.assert_called_once()
    remetente, destinatarios, corpo = server.sendmail.call_args[0]
    assert remetente == "alertas@leactis.com.br"
    assert destinatarios == ["cliente@exemplo.com"]
    mensagem = email.message_from_string(corpo)
    assert mensagem["Subject"] == "Assunto do alerta"
    texto = mensagem.get_payload()[0].get_payload(decode=True).decode("utf-8")
    assert "Corpo do e-mail" in texto


def test_send_email_uses_username_as_from_when_smtp_from_not_given():
    server = MagicMock()
    with patch("smtplib.SMTP") as mock_smtp:
        mock_smtp.return_value.__enter__.return_value = server
        send_email("cliente@exemplo.com", "Assunto", "Corpo", "smtp.exemplo.com", 587, "usuario@exemplo.com", "senha")

    remetente, _, _ = server.sendmail.call_args[0]
    assert remetente == "usuario@exemplo.com"


def test_send_email_raises_email_error_on_smtp_failure():
    with patch("smtplib.SMTP", side_effect=OSError("conexão recusada")):
        with pytest.raises(EmailError, match="Falha ao enviar e-mail"):
            send_email("cliente@exemplo.com", "Assunto", "Corpo", "smtp.exemplo.com", 587, "usuario", "senha")
