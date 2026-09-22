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

# Tipos cujo `vencimento` representa uma data de urgência (vencimento de DAS/
# parcela, ou validade de CND) — mesmo campo, o motivo do alerta muda por tipo.
TIPOS_COM_VENCIMENTO = {"das", "cnd", "parcelamento"}

MOTIVOS_VENCIMENTO = {
    "das": "das_vencendo",
    "cnd": "cnd_vencendo",
    "parcelamento": "parcelamento_vencendo",
}

# Sublimite do Simples Nacional: acima disso a empresa perde o benefício de
# recolher ICMS/ISS dentro do DAS (passa a apurar por fora). Teto: acima
# disso a empresa é excluída do regime no ano seguinte. Valores vigentes em
# 2026 — revisar se a legislação mudar.
SUBLIMITE_SIMPLES = 3_600_000.0
TETO_SIMPLES = 4_800_000.0
ALERTA_PROXIMIDADE_PCT = 0.8


@dataclass
class AlertItem:
    cnpj: storage.Cnpj
    finding: storage.Finding
    motivo: str  # "novo_achado", "das_vencendo", "cnd_vencendo" ou "parcelamento_vencendo"


@dataclass
class SublimiteAlertItem:
    cnpj: storage.Cnpj
    faturamento_12m: float
    label: str  # "proximo_sublimite" / "sublimite_estourado" / "proximo_teto" / "teto_estourado"


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
        if finding.tipo not in TIPOS_COM_VENCIMENTO:
            continue
        # "pago" não faz sentido pra CND (não é algo que se paga) — só DAS e
        # parcelamento pulam o alerta quando já quitados.
        if finding.tipo != "cnd" and finding.pago:
            continue
        dias = days_until(finding.vencimento, today=today)
        if dias is not None and dias <= dias_alerta:
            alerts.append(AlertItem(cnpj=cnpj, finding=finding, motivo=MOTIVOS_VENCIMENTO[finding.tipo]))
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


def _sublimite_label(faturamento_12m: float) -> str | None:
    if faturamento_12m >= TETO_SIMPLES:
        return "teto_estourado"
    if faturamento_12m >= TETO_SIMPLES * ALERTA_PROXIMIDADE_PCT:
        return "proximo_teto"
    if faturamento_12m >= SUBLIMITE_SIMPLES:
        return "sublimite_estourado"
    if faturamento_12m >= SUBLIMITE_SIMPLES * ALERTA_PROXIMIDADE_PCT:
        return "proximo_sublimite"
    return None


def check_sublimite_simples(conn: sqlite3.Connection, tenant_id: int, referencia: str) -> list[SublimiteAlertItem]:
    """Alerta CNPJs no regime Simples Nacional perto do sublimite/teto de
    faturamento acumulado nos últimos 12 meses (`referencia` = "YYYY-MM").

    Só considera CNPJs com `regime_tributario == "simples"` — os outros
    regimes não têm esse limite.
    """
    alerts: list[SublimiteAlertItem] = []
    for cnpj in storage.list_cnpjs(conn, tenant_id):
        if cnpj.regime_tributario != "simples":
            continue
        total = storage.faturamento_acumulado_12m(conn, cnpj.id, referencia)
        label = _sublimite_label(total)
        if label:
            alerts.append(SublimiteAlertItem(cnpj=cnpj, faturamento_12m=total, label=label))
    return alerts
