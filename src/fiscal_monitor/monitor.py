"""Motor de diff: compara um snapshot novo com o último salvo por CNPJ e
classifica cada achado (NOVA / RECORRENTE / RESOLVIDA), depois decide quais
merecem alerta.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from src.fiscal_monitor import storage
from src.fiscal_monitor.providers import RawFinding

STATUS_NOVA = "nova"
STATUS_RECORRENTE = "recorrente"
STATUS_RESOLVIDA = "resolvida"

DEFAULT_DIAS_ALERTA = 5


@dataclass
class AlertItem:
    cnpj: storage.Cnpj
    finding: storage.Finding
    motivo: str  # "novo_achado" ou "das_vencendo"


def _finding_key(finding) -> tuple[str, str, str]:
    return (finding.esfera, finding.tipo, finding.descricao)


def apply_snapshot(
    conn: sqlite3.Connection, cnpj: storage.Cnpj, provider_name: str, raw_findings: list[RawFinding]
) -> list[storage.Finding]:
    """Salva um novo snapshot pro CNPJ, classificando cada achado por
    comparação com o último snapshot salvo (achados resolvidos não contam
    como "aberto" pra fins de comparação — se reaparecerem, viram NOVA de
    novo). Retorna os findings salvos, já com status atribuído.
    """
    previous_snapshot_id = storage.latest_snapshot_id(conn, cnpj.id)
    previous_keys: set[tuple[str, str, str]] = set()
    if previous_snapshot_id is not None:
        previous_keys = {
            _finding_key(f)
            for f in storage.findings_for_snapshot(conn, previous_snapshot_id)
            if f.status != STATUS_RESOLVIDA
        }

    new_snapshot_id = storage.create_snapshot(conn, cnpj.id, provider_name)

    current_keys: set[tuple[str, str, str]] = set()
    saved: list[storage.Finding] = []
    for raw in raw_findings:
        key = _finding_key(raw)
        current_keys.add(key)
        status = STATUS_RECORRENTE if key in previous_keys else STATUS_NOVA
        finding_id = storage.add_finding(
            conn, new_snapshot_id, raw.esfera, raw.tipo, raw.descricao, raw.valor, raw.vencimento, raw.pago, status
        )
        saved.append(
            storage.Finding(
                id=finding_id,
                snapshot_id=new_snapshot_id,
                esfera=raw.esfera,
                tipo=raw.tipo,
                descricao=raw.descricao,
                valor=raw.valor,
                vencimento=raw.vencimento,
                pago=raw.pago,
                status=status,
            )
        )

    for esfera, tipo, descricao in previous_keys - current_keys:
        finding_id = storage.add_finding(
            conn, new_snapshot_id, esfera, tipo, descricao, None, None, False, STATUS_RESOLVIDA
        )
        saved.append(
            storage.Finding(
                id=finding_id,
                snapshot_id=new_snapshot_id,
                esfera=esfera,
                tipo=tipo,
                descricao=descricao,
                valor=None,
                vencimento=None,
                pago=False,
                status=STATUS_RESOLVIDA,
            )
        )

    return saved


def days_until(vencimento: str | None, today: date | None = None) -> int | None:
    if not vencimento:
        return None
    try:
        due = datetime.strptime(vencimento, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (due - (today or date.today())).days


def findings_needing_alert(
    cnpj: storage.Cnpj,
    findings: list[storage.Finding],
    dias_alerta: int = DEFAULT_DIAS_ALERTA,
    today: date | None = None,
) -> list[AlertItem]:
    alerts = []
    for finding in findings:
        if finding.status == STATUS_NOVA:
            alerts.append(AlertItem(cnpj=cnpj, finding=finding, motivo="novo_achado"))
            continue
        if finding.tipo == "das" and not finding.pago:
            dias = days_until(finding.vencimento, today=today)
            if dias is not None and dias <= dias_alerta:
                alerts.append(AlertItem(cnpj=cnpj, finding=finding, motivo="das_vencendo"))
    return alerts


def check_tenant(
    conn: sqlite3.Connection, tenant_id: int, dias_alerta: int = DEFAULT_DIAS_ALERTA, today: date | None = None
) -> list[AlertItem]:
    """Roda o motor de alertas sobre o último snapshot já salvo de cada CNPJ
    do tenant — não busca dado novo (isso é feito por um provider via
    import de snapshot, antes de rodar o check).
    """
    alerts: list[AlertItem] = []
    for cnpj in storage.list_cnpjs(conn, tenant_id):
        snapshot_id = storage.latest_snapshot_id(conn, cnpj.id)
        if snapshot_id is None:
            continue
        findings = storage.findings_for_snapshot(conn, snapshot_id)
        alerts.extend(findings_needing_alert(cnpj, findings, dias_alerta=dias_alerta, today=today))
    return alerts
