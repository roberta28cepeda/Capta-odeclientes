"""Monta o resumo de alertas fiscais e dispara pro contato de WhatsApp do
tenant, reusando o mesmo client do módulo `whatsapp`.
"""

from __future__ import annotations

from src.fiscal_monitor.monitor import AlertItem
from src.fiscal_monitor.storage import Tenant
from src.whatsapp.client import send_pdf, send_text_message

MOTIVO_LABELS = {
    "novo_achado": "Novo achado",
    "das_vencendo": "DAS a vencer",
}


def format_alert_text(item: AlertItem) -> str:
    label = MOTIVO_LABELS.get(item.motivo, item.motivo)
    linha = f"[{label}] {item.cnpj.razao_social or item.cnpj.cnpj} ({item.cnpj.cnpj})\n"
    linha += f"{item.finding.esfera.capitalize()} / {item.finding.tipo.upper()}: {item.finding.descricao}"
    if item.finding.valor:
        linha += f" — R$ {item.finding.valor:,.2f}"
    if item.finding.vencimento:
        linha += f" — vencimento {item.finding.vencimento}"
    return linha


def format_alerts_summary(tenant: Tenant, alerts: list[AlertItem]) -> str:
    if not alerts:
        return f"Nenhum alerta novo para {tenant.nome}."
    header = f"{len(alerts)} alerta(s) fiscal(is) para {tenant.nome}:\n\n"
    return header + "\n\n".join(format_alert_text(item) for item in alerts)


def send_whatsapp_alert(
    tenant: Tenant, alerts: list[AlertItem], phone_number_id: str, access_token: str
) -> dict | None:
    """Envia o resumo de alertas por WhatsApp pro contato do tenant.

    Retorna None (sem enviar nada) se o tenant não tem WhatsApp cadastrado
    ou se não há alertas.
    """
    if not tenant.contato_whatsapp or not alerts:
        return None
    text = format_alerts_summary(tenant, alerts)
    return send_text_message(tenant.contato_whatsapp, text, phone_number_id, access_token)


def send_whatsapp_report(tenant: Tenant, pdf_path: str, phone_number_id: str, access_token: str) -> dict | None:
    """Envia o relatório de carteira em PDF pro contato do tenant.

    Retorna None (sem enviar nada) se o tenant não tem WhatsApp cadastrado.
    """
    if not tenant.contato_whatsapp:
        return None
    caption = f"Relatório fiscal — {tenant.nome}"
    return send_pdf(pdf_path, tenant.contato_whatsapp, phone_number_id, access_token, caption=caption)
