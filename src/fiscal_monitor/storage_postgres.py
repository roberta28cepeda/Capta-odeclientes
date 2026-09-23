"""Backend Postgres — usado em produção quando alguma variável de conexão
está definida (`DATABASE_URL`, ou as que o Vercel/Neon injetam
automaticamente ao conectar um banco: `POSTGRES_URL`,
`POSTGRES_URL_NON_POOLING`). Cria o próprio schema no primeiro connect,
igual ao backend SQLite — não depende de migration rodada por fora.

Datas ficam guardadas como TEXT (ISO), não TIMESTAMPTZ/DATE nativos —
de propósito, pra manter o formato de linha idêntico ao do backend SQLite
(toda comparação de data já é feita em Python, não em SQL).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

from src.fiscal_monitor.models import Cnpj, Finding, Tenant

DEFAULT_DB_PATH = "output/fiscal_monitor.db"  # não usado neste backend; mantido por simetria de assinatura

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    contato_whatsapp TEXT,
    plano TEXT,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cnpjs (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cnpj TEXT NOT NULL,
    razao_social TEXT,
    nome_fantasia TEXT,
    ativo BOOLEAN NOT NULL DEFAULT true,
    regime_tributario TEXT,
    UNIQUE(tenant_id, cnpj)
);

CREATE TABLE IF NOT EXISTS faturamentos (
    id SERIAL PRIMARY KEY,
    cnpj_id INTEGER NOT NULL REFERENCES cnpjs(id),
    competencia TEXT NOT NULL,
    valor DOUBLE PRECISION NOT NULL,
    UNIQUE(cnpj_id, competencia)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id SERIAL PRIMARY KEY,
    cnpj_id INTEGER NOT NULL REFERENCES cnpjs(id),
    verificado_em TEXT NOT NULL,
    provider TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id SERIAL PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    esfera TEXT NOT NULL,
    tipo TEXT NOT NULL,
    descricao TEXT NOT NULL,
    valor DOUBLE PRECISION,
    vencimento TEXT,
    pago BOOLEAN NOT NULL DEFAULT false,
    status TEXT NOT NULL
);
"""

_CONNECTION_ENV_VARS = ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_URL_NON_POOLING")


def _connection_string() -> str:
    for var in _CONNECTION_ENV_VARS:
        value = os.environ.get(var)
        if value:
            return value
    raise RuntimeError(
        "Nenhuma variável de conexão Postgres encontrada "
        f"({', '.join(_CONNECTION_ENV_VARS)}). Configure isso no ambiente."
    )


def connect(db_path: str | None = None) -> psycopg2.extensions.connection:
    conn = psycopg2.connect(_connection_string(), cursor_factory=psycopg2.extras.RealDictCursor)
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()
    return conn


def create_tenant(conn, nome: str, contato_whatsapp: str | None = None, plano: str | None = None) -> Tenant:
    criado_em = datetime.now(timezone.utc).isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (nome, contato_whatsapp, plano, criado_em) VALUES (%s, %s, %s, %s) RETURNING id",
            (nome, contato_whatsapp, plano, criado_em),
        )
        tenant_id = cur.fetchone()["id"]
    conn.commit()
    return Tenant(id=tenant_id, nome=nome, contato_whatsapp=contato_whatsapp, plano=plano, criado_em=criado_em)


def get_tenant(conn, tenant_id: int) -> Tenant | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM tenants WHERE id = %s", (tenant_id,))
        row = cur.fetchone()
    return _row_to_tenant(row) if row else None


def list_tenants(conn) -> list[Tenant]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM tenants ORDER BY id")
        rows = cur.fetchall()
    return [_row_to_tenant(row) for row in rows]


def _row_to_tenant(row) -> Tenant:
    return Tenant(
        id=row["id"],
        nome=row["nome"],
        contato_whatsapp=row["contato_whatsapp"],
        plano=row["plano"],
        criado_em=row["criado_em"],
    )


def upsert_cnpj(
    conn,
    tenant_id: int,
    cnpj: str,
    razao_social: str | None = None,
    nome_fantasia: str | None = None,
    regime_tributario: str | None = None,
) -> Cnpj:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO cnpjs (tenant_id, cnpj, razao_social, nome_fantasia, ativo, regime_tributario)
            VALUES (%s, %s, %s, %s, true, %s)
            ON CONFLICT (tenant_id, cnpj) DO UPDATE SET
                razao_social = EXCLUDED.razao_social,
                nome_fantasia = EXCLUDED.nome_fantasia,
                regime_tributario = EXCLUDED.regime_tributario
            """,
            (tenant_id, cnpj, razao_social, nome_fantasia, regime_tributario),
        )
    conn.commit()
    return get_cnpj_by_number(conn, tenant_id, cnpj)  # type: ignore[return-value]


def list_cnpjs(conn, tenant_id: int) -> list[Cnpj]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM cnpjs WHERE tenant_id = %s ORDER BY id", (tenant_id,))
        rows = cur.fetchall()
    return [_row_to_cnpj(row) for row in rows]


def get_cnpj_by_number(conn, tenant_id: int, cnpj: str) -> Cnpj | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM cnpjs WHERE tenant_id = %s AND cnpj = %s", (tenant_id, cnpj))
        row = cur.fetchone()
    return _row_to_cnpj(row) if row else None


def get_cnpj(conn, cnpj_id: int) -> Cnpj | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM cnpjs WHERE id = %s", (cnpj_id,))
        row = cur.fetchone()
    return _row_to_cnpj(row) if row else None


def _row_to_cnpj(row) -> Cnpj:
    return Cnpj(
        id=row["id"],
        tenant_id=row["tenant_id"],
        cnpj=row["cnpj"],
        razao_social=row["razao_social"],
        nome_fantasia=row["nome_fantasia"],
        ativo=row["ativo"],
        regime_tributario=row["regime_tributario"],
    )


def create_snapshot(conn, cnpj_id: int, provider: str) -> int:
    verificado_em = datetime.now(timezone.utc).isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO snapshots (cnpj_id, verificado_em, provider) VALUES (%s, %s, %s) RETURNING id",
            (cnpj_id, verificado_em, provider),
        )
        snapshot_id = cur.fetchone()["id"]
    conn.commit()
    return snapshot_id


def add_finding(
    conn,
    snapshot_id: int,
    esfera: str,
    tipo: str,
    descricao: str,
    valor: float | None,
    vencimento: str | None,
    pago: bool,
    status: str,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO findings (snapshot_id, esfera, tipo, descricao, valor, vencimento, pago, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (snapshot_id, esfera, tipo, descricao, valor, vencimento, pago, status),
        )
        finding_id = cur.fetchone()["id"]
    conn.commit()
    return finding_id


def latest_snapshot_id(conn, cnpj_id: int) -> int | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM snapshots WHERE cnpj_id = %s ORDER BY id DESC LIMIT 1", (cnpj_id,))
        row = cur.fetchone()
    return row["id"] if row else None


def findings_for_snapshot(conn, snapshot_id: int) -> list[Finding]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM findings WHERE snapshot_id = %s ORDER BY id", (snapshot_id,))
        rows = cur.fetchall()
    return [_row_to_finding(row) for row in rows]


def _row_to_finding(row) -> Finding:
    return Finding(
        id=row["id"],
        snapshot_id=row["snapshot_id"],
        esfera=row["esfera"],
        tipo=row["tipo"],
        descricao=row["descricao"],
        valor=row["valor"],
        vencimento=row["vencimento"],
        pago=row["pago"],
        status=row["status"],
    )


def record_faturamento(conn, cnpj_id: int, competencia: str, valor: float) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO faturamentos (cnpj_id, competencia, valor)
            VALUES (%s, %s, %s)
            ON CONFLICT (cnpj_id, competencia) DO UPDATE SET valor = EXCLUDED.valor
            """,
            (cnpj_id, competencia, valor),
        )
    conn.commit()


def _last_12_competencias(referencia: str) -> list[str]:
    year, month = (int(p) for p in referencia.split("-"))
    competencias = []
    for i in range(12):
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        competencias.append(f"{y:04d}-{m:02d}")
    return competencias


def faturamento_acumulado_12m(conn, cnpj_id: int, referencia: str) -> float:
    competencias = _last_12_competencias(referencia)
    placeholders = ",".join(["%s"] * len(competencias))
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COALESCE(SUM(valor), 0) AS total FROM faturamentos "
            f"WHERE cnpj_id = %s AND competencia IN ({placeholders})",
            (cnpj_id, *competencias),
        )
        row = cur.fetchone()
    return float(row["total"])


def all_findings_for_cnpj(conn, cnpj_id: int) -> list[tuple[str, str, Finding]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT snapshots.verificado_em AS verificado_em, snapshots.provider AS provider, findings.*
            FROM findings
            JOIN snapshots ON snapshots.id = findings.snapshot_id
            WHERE snapshots.cnpj_id = %s
            ORDER BY snapshots.id DESC, findings.id
            """,
            (cnpj_id,),
        )
        rows = cur.fetchall()
    return [(row["verificado_em"], row["provider"], _row_to_finding(row)) for row in rows]


def findings_by_cnpj_for_tenant(conn, tenant_id: int) -> list[tuple[Cnpj, list[Finding]]]:
    result = []
    for cnpj in list_cnpjs(conn, tenant_id):
        snapshot_id = latest_snapshot_id(conn, cnpj.id)
        findings = findings_for_snapshot(conn, snapshot_id) if snapshot_id is not None else []
        open_findings = [f for f in findings if f.status != "resolvida"]
        result.append((cnpj, open_findings))
    return result
