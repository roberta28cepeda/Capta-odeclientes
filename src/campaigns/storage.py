"""Escolhe o backend de persistência: Postgres em produção (mesma env var
que o `fiscal_monitor` usa — os dois módulos dividem o mesmo banco
Postgres, em tabelas com prefixo diferente), SQLite localmente. Resto do
módulo importa só `storage`, sem saber qual dos dois está por trás.
"""

from __future__ import annotations

import os

from src.campaigns.models import Envio, Evento, Lead, Template  # noqa: F401

if os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or os.environ.get("POSTGRES_URL_NON_POOLING"):
    from src.campaigns.storage_postgres import (  # noqa: F401
        DEFAULT_DB_PATH,
        add_evento,
        bulk_create_leads,
        connect,
        create_envio,
        create_lead,
        envios_de_hoje_por_tese,
        envios_desde,
        envios_do_lead,
        eventos_desde,
        eventos_do_envio,
        get_envio_by_token,
        get_lead,
        get_lead_by_cnpj,
        get_template,
        leads_pendentes_whatsapp,
        leads_sem_email,
        leads_sem_telefone,
        list_leads,
        list_template_teses,
        list_templates,
        list_teses,
        set_lead_email,
        set_lead_telefone,
        set_lead_whatsapp_contatado,
        set_template,
    )
else:
    from src.campaigns.storage_sqlite import (  # noqa: F401
        DEFAULT_DB_PATH,
        add_evento,
        bulk_create_leads,
        connect,
        create_envio,
        create_lead,
        envios_de_hoje_por_tese,
        envios_desde,
        envios_do_lead,
        eventos_desde,
        eventos_do_envio,
        get_envio_by_token,
        get_lead,
        get_lead_by_cnpj,
        get_template,
        leads_pendentes_whatsapp,
        leads_sem_email,
        leads_sem_telefone,
        list_leads,
        list_template_teses,
        list_templates,
        list_teses,
        set_lead_email,
        set_lead_telefone,
        set_lead_whatsapp_contatado,
        set_template,
    )
