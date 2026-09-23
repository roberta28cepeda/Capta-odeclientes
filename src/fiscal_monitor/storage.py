"""Escolhe o backend de persistência: Postgres em produção (quando
`DATABASE_URL`/`POSTGRES_URL`/`POSTGRES_URL_NON_POOLING` está definida —
é o que o Vercel injeta ao conectar um banco), SQLite localmente (dev,
testes, CLI sem banco configurado). Resto do módulo (`monitor.py`,
`server.py`, `cli.py`, `alerts.py`, `pdf.py`) importa só `storage`, sem
saber qual dos dois está por trás — mesma API nos dois.
"""

from __future__ import annotations

import os

from src.fiscal_monitor.models import Cnpj, Finding, REGIMES_TRIBUTARIOS, Tenant  # noqa: F401

if os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or os.environ.get("POSTGRES_URL_NON_POOLING"):
    from src.fiscal_monitor.storage_postgres import (  # noqa: F401
        DEFAULT_DB_PATH,
        add_finding,
        all_findings_for_cnpj,
        connect,
        create_snapshot,
        create_tenant,
        faturamento_acumulado_12m,
        findings_by_cnpj_for_tenant,
        findings_for_snapshot,
        get_cnpj,
        get_cnpj_by_number,
        get_tenant,
        latest_snapshot_id,
        list_cnpjs,
        list_tenants,
        record_faturamento,
        upsert_cnpj,
    )
else:
    from src.fiscal_monitor.storage_sqlite import (  # noqa: F401
        DEFAULT_DB_PATH,
        add_finding,
        all_findings_for_cnpj,
        connect,
        create_snapshot,
        create_tenant,
        faturamento_acumulado_12m,
        findings_by_cnpj_for_tenant,
        findings_for_snapshot,
        get_cnpj,
        get_cnpj_by_number,
        get_tenant,
        latest_snapshot_id,
        list_cnpjs,
        list_tenants,
        record_faturamento,
        upsert_cnpj,
    )
