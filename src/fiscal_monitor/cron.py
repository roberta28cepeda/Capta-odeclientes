"""Checagem automática agendada: roda o motor de alertas pra todos os
tenants de uma vez e dispara WhatsApp/e-mail pra quem tem contato e
credenciais configuradas — sem precisar rodar `--check` manualmente tenant
por tenant. Pensado pra ser chamado por um scheduler externo (Vercel Cron)
batendo no endpoint protegido `/cron/check-all` de `server.py`.

Não importa snapshot novo nem chama nenhum provider fiscal — só roda o
motor de alertas sobre o que já foi importado (igual `--check` no CLI).
"""

from __future__ import annotations

import os
from datetime import date

from src.fiscal_monitor import alerts, monitor, storage


def check_all_tenants(
    conn, dias_alerta: int = monitor.DEFAULT_DIAS_ALERTA, referencia: str | None = None
) -> list[dict]:
    """Roda o check de cada tenant cadastrado e envia alerta por
    WhatsApp/e-mail quando o tenant tiver o contato cadastrado e as
    credenciais (`WHATSAPP_*`/`SMTP_*`) existirem no ambiente. Um erro num
    tenant (ex.: falha ao enviar WhatsApp) não interrompe os demais —
    fica registrado no resultado daquele tenant.
    """
    referencia = referencia or date.today().strftime("%Y-%m")

    whatsapp_token = os.environ.get("WHATSAPP_ACCESS_TOKEN")
    whatsapp_phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    whatsapp_configurado = bool(whatsapp_token and whatsapp_phone_id)

    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = os.environ.get("SMTP_PORT")
    smtp_username = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_from = os.environ.get("SMTP_FROM")
    smtp_configurado = bool(smtp_host and smtp_port and smtp_username and smtp_password)

    resultados = []
    for tenant in storage.list_tenants(conn):
        resultado = {
            "tenant_id": tenant.id,
            "nome": tenant.nome,
            "alertas": 0,
            "sublimite_alertas": 0,
            "enviado_whatsapp": False,
            "enviado_email": False,
            "erro": None,
        }
        try:
            alert_items = monitor.check_tenant(conn, tenant.id, dias_alerta=dias_alerta)
            sublimite_items = monitor.check_sublimite_simples(conn, tenant.id, referencia)
            resultado["alertas"] = len(alert_items)
            resultado["sublimite_alertas"] = len(sublimite_items)

            if whatsapp_configurado and alert_items:
                envio = alerts.send_whatsapp_alert(tenant, alert_items, whatsapp_phone_id, whatsapp_token)
                resultado["enviado_whatsapp"] = envio is not None

            if smtp_configurado and alert_items:
                resultado["enviado_email"] = alerts.send_email_alert(
                    tenant, alert_items, smtp_host, int(smtp_port), smtp_username, smtp_password, smtp_from=smtp_from
                )
        except Exception as exc:
            resultado["erro"] = str(exc)
        resultados.append(resultado)
    return resultados
