"""Persistência SQLite do módulo de monitoramento fiscal.

Primeiro módulo do repositório a precisar de um banco: gerencia os
escritórios contábeis (tenants), a carteira de CNPJs monitorados de cada
um, e o histórico de snapshots/achados fiscais usado pelo motor de diff em
`monitor.py`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

DEFAULT_DB_PATH = "output/fiscal_monitor.db"

REGIMES_TRIBUTARIOS = {"mei", "simples", "presumido", "real"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    contato_whatsapp TEXT,
    plano TEXT,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cnpjs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cnpj TEXT NOT NULL,
    razao_social TEXT,
    nome_fantasia TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    regime_tributario TEXT,
    UNIQUE(tenant_id, cnpj)
);

CREATE TABLE IF NOT EXISTS faturamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_id INTEGER NOT NULL REFERENCES cnpjs(id),
    competencia TEXT NOT NULL,
    valor REAL NOT NULL,
    UNIQUE(cnpj_id, competencia)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_id INTEGER NOT NULL REFERENCES cnpjs(id),
    verificado_em TEXT NOT NULL,
    provider TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    esfera TEXT NOT NULL,
    tipo TEXT NOT NULL,
    descricao TEXT NOT NULL,
    valor REAL,
    vencimento TEXT,
    pago INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL
);
"""


@dataclass
class Tenant:
    id: int
    nome: str
    contato_whatsapp: str | None
    plano: str | None
    criado_em: str


@dataclass
class Cnpj:
    id: int
    tenant_id: int
    cnpj: str
    razao_social: str | None
    nome_fantasia: str | None
    ativo: bool
    regime_tributario: str | None = None


@dataclass
class Finding:
    id: int | None
    snapshot_id: int
    esfera: str
    tipo: str
    descricao: str
    valor: float | None
    vencimento: str | None
    pago: bool
    status: str


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Adiciona colunas novas em bancos criados por uma versão anterior do schema.

    `CREATE TABLE IF NOT EXISTS` já cobre tabelas novas (ex: `faturamentos`)
    — isso aqui só cobre coluna nova em tabela existente, que o SQLite não
    tem `ADD COLUMN IF NOT EXISTS` para.
    """
    try:
        conn.execute("ALTER TABLE cnpjs ADD COLUMN regime_tributario TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # coluna já existe


def create_tenant(
    conn: sqlite3.Connection, nome: str, contato_whatsapp: str | None = None, plano: str | None = None
) -> Tenant:
    criado_em = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO tenants (nome, contato_whatsapp, plano, criado_em) VALUES (?, ?, ?, ?)",
        (nome, contato_whatsapp, plano, criado_em),
    )
    conn.commit()
    return Tenant(
        id=cursor.lastrowid, nome=nome, contato_whatsapp=contato_whatsapp, plano=plano, criado_em=criado_em
    )


def get_tenant(conn: sqlite3.Connection, tenant_id: int) -> Tenant | None:
    row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    return _row_to_tenant(row) if row else None


def list_tenants(conn: sqlite3.Connection) -> list[Tenant]:
    rows = conn.execute("SELECT * FROM tenants ORDER BY id").fetchall()
    return [_row_to_tenant(row) for row in rows]


def _row_to_tenant(row: sqlite3.Row) -> Tenant:
    return Tenant(
        id=row["id"],
        nome=row["nome"],
        contato_whatsapp=row["contato_whatsapp"],
        plano=row["plano"],
        criado_em=row["criado_em"],
    )


def upsert_cnpj(
    conn: sqlite3.Connection,
    tenant_id: int,
    cnpj: str,
    razao_social: str | None = None,
    nome_fantasia: str | None = None,
    regime_tributario: str | None = None,
) -> Cnpj:
    conn.execute(
        """
        INSERT INTO cnpjs (tenant_id, cnpj, razao_social, nome_fantasia, ativo, regime_tributario)
        VALUES (?, ?, ?, ?, 1, ?)
        ON CONFLICT(tenant_id, cnpj) DO UPDATE SET
            razao_social = excluded.razao_social,
            nome_fantasia = excluded.nome_fantasia,
            regime_tributario = excluded.regime_tributario
        """,
        (tenant_id, cnpj, razao_social, nome_fantasia, regime_tributario),
    )
    conn.commit()
    return get_cnpj_by_number(conn, tenant_id, cnpj)  # type: ignore[return-value]


def list_cnpjs(conn: sqlite3.Connection, tenant_id: int) -> list[Cnpj]:
    rows = conn.execute("SELECT * FROM cnpjs WHERE tenant_id = ? ORDER BY id", (tenant_id,)).fetchall()
    return [_row_to_cnpj(row) for row in rows]


def get_cnpj_by_number(conn: sqlite3.Connection, tenant_id: int, cnpj: str) -> Cnpj | None:
    row = conn.execute("SELECT * FROM cnpjs WHERE tenant_id = ? AND cnpj = ?", (tenant_id, cnpj)).fetchone()
    return _row_to_cnpj(row) if row else None


def get_cnpj(conn: sqlite3.Connection, cnpj_id: int) -> Cnpj | None:
    row = conn.execute("SELECT * FROM cnpjs WHERE id = ?", (cnpj_id,)).fetchone()
    return _row_to_cnpj(row) if row else None


def _row_to_cnpj(row: sqlite3.Row) -> Cnpj:
    return Cnpj(
        id=row["id"],
        tenant_id=row["tenant_id"],
        cnpj=row["cnpj"],
        razao_social=row["razao_social"],
        nome_fantasia=row["nome_fantasia"],
        ativo=bool(row["ativo"]),
        regime_tributario=row["regime_tributario"],
    )


def create_snapshot(conn: sqlite3.Connection, cnpj_id: int, provider: str) -> int:
    verificado_em = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO snapshots (cnpj_id, verificado_em, provider) VALUES (?, ?, ?)",
        (cnpj_id, verificado_em, provider),
    )
    conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def add_finding(
    conn: sqlite3.Connection,
    snapshot_id: int,
    esfera: str,
    tipo: str,
    descricao: str,
    valor: float | None,
    vencimento: str | None,
    pago: bool,
    status: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO findings (snapshot_id, esfera, tipo, descricao, valor, vencimento, pago, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (snapshot_id, esfera, tipo, descricao, valor, vencimento, int(pago), status),
    )
    conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def latest_snapshot_id(conn: sqlite3.Connection, cnpj_id: int) -> int | None:
    row = conn.execute(
        "SELECT id FROM snapshots WHERE cnpj_id = ? ORDER BY id DESC LIMIT 1", (cnpj_id,)
    ).fetchone()
    return row["id"] if row else None


def findings_for_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> list[Finding]:
    rows = conn.execute(
        "SELECT * FROM findings WHERE snapshot_id = ? ORDER BY id", (snapshot_id,)
    ).fetchall()
    return [_row_to_finding(row) for row in rows]


def _row_to_finding(row: sqlite3.Row) -> Finding:
    return Finding(
        id=row["id"],
        snapshot_id=row["snapshot_id"],
        esfera=row["esfera"],
        tipo=row["tipo"],
        descricao=row["descricao"],
        valor=row["valor"],
        vencimento=row["vencimento"],
        pago=bool(row["pago"]),
        status=row["status"],
    )


def record_faturamento(conn: sqlite3.Connection, cnpj_id: int, competencia: str, valor: float) -> None:
    """Registra o faturamento de uma competência ("YYYY-MM"). Sobrescreve se já existir."""
    conn.execute(
        """
        INSERT INTO faturamentos (cnpj_id, competencia, valor)
        VALUES (?, ?, ?)
        ON CONFLICT(cnpj_id, competencia) DO UPDATE SET valor = excluded.valor
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


def faturamento_acumulado_12m(conn: sqlite3.Connection, cnpj_id: int, referencia: str) -> float:
    """Soma o faturamento dos 12 meses terminando em `referencia` ("YYYY-MM"), inclusive."""
    competencias = _last_12_competencias(referencia)
    placeholders = ",".join("?" for _ in competencias)
    row = conn.execute(
        f"SELECT COALESCE(SUM(valor), 0) AS total FROM faturamentos "
        f"WHERE cnpj_id = ? AND competencia IN ({placeholders})",
        (cnpj_id, *competencias),
    ).fetchone()
    return row["total"]


def all_findings_for_cnpj(conn: sqlite3.Connection, cnpj_id: int) -> list[tuple[str, str, Finding]]:
    """Histórico completo (todas as rodadas de checagem) de um CNPJ, mais recente primeiro.

    Retorna (verificado_em, provider, finding) — inclui achados `resolvida`,
    ao contrário de `findings_by_cnpj_for_tenant` (que só mostra o que está
    aberto agora).
    """
    rows = conn.execute(
        """
        SELECT snapshots.verificado_em AS verificado_em, snapshots.provider AS provider, findings.*
        FROM findings
        JOIN snapshots ON snapshots.id = findings.snapshot_id
        WHERE snapshots.cnpj_id = ?
        ORDER BY snapshots.id DESC, findings.id
        """,
        (cnpj_id,),
    ).fetchall()
    return [(row["verificado_em"], row["provider"], _row_to_finding(row)) for row in rows]


def findings_by_cnpj_for_tenant(conn: sqlite3.Connection, tenant_id: int) -> list[tuple[Cnpj, list[Finding]]]:
    """Achados em aberto (não `resolvida`) do último snapshot de cada CNPJ do tenant.

    Inclui CNPJs sem nenhum achado (lista vazia), para o relatório mostrar
    a carteira inteira, não só quem tem pendência.
    """
    result = []
    for cnpj in list_cnpjs(conn, tenant_id):
        snapshot_id = latest_snapshot_id(conn, cnpj.id)
        findings = findings_for_snapshot(conn, snapshot_id) if snapshot_id is not None else []
        open_findings = [f for f in findings if f.status != "resolvida"]
        result.append((cnpj, open_findings))
    return result
