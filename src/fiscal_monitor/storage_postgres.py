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
import secrets
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

from src.fiscal_monitor.models import AdminUser, Certidao, Cnpj, Finding, Obrigacao, Tenant

DEFAULT_DB_PATH = "output/fiscal_monitor.db"  # não usado neste backend; mantido por simetria de assinatura

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    contato_whatsapp TEXT,
    plano TEXT,
    criado_em TEXT NOT NULL,
    acesso_token TEXT NOT NULL DEFAULT '',
    contato_email TEXT
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

CREATE TABLE IF NOT EXISTS admin_users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nome TEXT,
    criado_em TEXT NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS obrigacoes (
    id SERIAL PRIMARY KEY,
    cnpj_id INTEGER NOT NULL REFERENCES cnpjs(id),
    tipo TEXT NOT NULL,
    vencimento TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendente'
);

CREATE TABLE IF NOT EXISTS certidoes (
    id SERIAL PRIMARY KEY,
    cnpj_id INTEGER NOT NULL REFERENCES cnpjs(id),
    orgao TEXT NOT NULL,
    numero TEXT,
    emitida_em TEXT NOT NULL,
    valida_ate TEXT NOT NULL,
    arquivo_nome TEXT NOT NULL,
    arquivo_conteudo BYTEA NOT NULL,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pgfn_dividas_abertas (
    numero_inscricao TEXT PRIMARY KEY,
    cnpj TEXT NOT NULL,
    uf TEXT,
    receita_principal TEXT,
    situacao_inscricao TEXT NOT NULL,
    data_inscricao TEXT,
    indicador_ajuizado BOOLEAN NOT NULL DEFAULT false,
    valor_consolidado DOUBLE PRECISION,
    base_referencia TEXT NOT NULL,
    importado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS pgfn_dividas_abertas_cnpj_idx ON pgfn_dividas_abertas(cnpj);
"""

_CONNECTION_ENV_VARS = ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_URL_NON_POOLING")

# `ALTER TABLE` pede lock exclusivo — rodar isso em todo connect() serializaria
# (ou travaria) requisições concorrentes num ambiente serverless. Roda só uma
# vez por processo "quente"; correto porque um deployment usa sempre o mesmo
# DATABASE_URL durante seu tempo de vida.
_schema_ready = False


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
    global _schema_ready
    conn = psycopg2.connect(_connection_string(), cursor_factory=psycopg2.extras.RealDictCursor)
    if not _schema_ready:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
            cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS acesso_token TEXT NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS contato_email TEXT")
            cur.execute("ALTER TABLE cnpjs ADD COLUMN IF NOT EXISTS uf TEXT")
            cur.execute(
                "UPDATE tenants SET acesso_token = md5(random()::text || id::text) WHERE acesso_token = ''"
            )
        conn.commit()
        _schema_ready = True
    return conn


def create_tenant(
    conn,
    nome: str,
    contato_whatsapp: str | None = None,
    plano: str | None = None,
    contato_email: str | None = None,
) -> Tenant:
    criado_em = datetime.now(timezone.utc).isoformat()
    acesso_token = secrets.token_urlsafe(24)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (nome, contato_whatsapp, plano, criado_em, acesso_token, contato_email)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (nome, contato_whatsapp, plano, criado_em, acesso_token, contato_email),
        )
        tenant_id = cur.fetchone()["id"]
    conn.commit()
    return Tenant(
        id=tenant_id,
        nome=nome,
        contato_whatsapp=contato_whatsapp,
        plano=plano,
        criado_em=criado_em,
        acesso_token=acesso_token,
        contato_email=contato_email,
    )


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
        acesso_token=row["acesso_token"],
        contato_email=row["contato_email"],
    )


def upsert_cnpj(
    conn,
    tenant_id: int,
    cnpj: str,
    razao_social: str | None = None,
    nome_fantasia: str | None = None,
    regime_tributario: str | None = None,
    uf: str | None = None,
) -> Cnpj:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO cnpjs (tenant_id, cnpj, razao_social, nome_fantasia, ativo, regime_tributario, uf)
            VALUES (%s, %s, %s, %s, true, %s, %s)
            ON CONFLICT (tenant_id, cnpj) DO UPDATE SET
                razao_social = EXCLUDED.razao_social,
                nome_fantasia = EXCLUDED.nome_fantasia,
                regime_tributario = EXCLUDED.regime_tributario,
                uf = COALESCE(EXCLUDED.uf, cnpjs.uf)
            """,
            (tenant_id, cnpj, razao_social, nome_fantasia, regime_tributario, uf),
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
        uf=row["uf"],
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


def create_admin_user(conn, username: str, password_hash: str, nome: str | None = None) -> AdminUser:
    criado_em = datetime.now(timezone.utc).isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO admin_users (username, password_hash, nome, criado_em, ativo) VALUES (%s, %s, %s, %s, true) RETURNING id",
            (username, password_hash, nome, criado_em),
        )
        new_id = cur.fetchone()["id"]
    conn.commit()
    return AdminUser(id=new_id, username=username, password_hash=password_hash, nome=nome, criado_em=criado_em, ativo=True)


def get_admin_user_by_username(conn, username: str) -> AdminUser | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM admin_users WHERE username = %s", (username,))
        row = cur.fetchone()
    return _row_to_admin_user(row) if row else None


def list_admin_users(conn) -> list[AdminUser]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM admin_users ORDER BY id")
        rows = cur.fetchall()
    return [_row_to_admin_user(row) for row in rows]


def set_admin_user_ativo(conn, user_id: int, ativo: bool) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE admin_users SET ativo = %s WHERE id = %s", (ativo, user_id))
    conn.commit()


def _row_to_admin_user(row) -> AdminUser:
    return AdminUser(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        nome=row["nome"],
        criado_em=row["criado_em"],
        ativo=row["ativo"],
    )


def create_obrigacao(conn, cnpj_id: int, tipo: str, vencimento: str) -> Obrigacao:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO obrigacoes (cnpj_id, tipo, vencimento, status) VALUES (%s, %s, %s, 'pendente') RETURNING id",
            (cnpj_id, tipo, vencimento),
        )
        obrigacao_id = cur.fetchone()["id"]
    conn.commit()
    return Obrigacao(id=obrigacao_id, cnpj_id=cnpj_id, tipo=tipo, vencimento=vencimento, status="pendente")


def list_obrigacoes(conn, cnpj_id: int) -> list[Obrigacao]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM obrigacoes WHERE cnpj_id = %s ORDER BY vencimento", (cnpj_id,))
        rows = cur.fetchall()
    return [_row_to_obrigacao(row) for row in rows]


def marcar_obrigacao_entregue(conn, obrigacao_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE obrigacoes SET status = 'entregue' WHERE id = %s", (obrigacao_id,))
    conn.commit()


def get_obrigacao(conn, obrigacao_id: int) -> Obrigacao | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM obrigacoes WHERE id = %s", (obrigacao_id,))
        row = cur.fetchone()
    return _row_to_obrigacao(row) if row else None


def _row_to_obrigacao(row) -> Obrigacao:
    return Obrigacao(id=row["id"], cnpj_id=row["cnpj_id"], tipo=row["tipo"], vencimento=row["vencimento"], status=row["status"])


def create_certidao(
    conn, cnpj_id: int, orgao: str, numero: str | None, emitida_em: str, valida_ate: str, arquivo_nome: str,
    arquivo_conteudo: bytes,
) -> Certidao:
    criado_em = datetime.now(timezone.utc).isoformat()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO certidoes (cnpj_id, orgao, numero, emitida_em, valida_ate, arquivo_nome, arquivo_conteudo, criado_em)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (cnpj_id, orgao, numero, emitida_em, valida_ate, arquivo_nome, psycopg2.Binary(arquivo_conteudo), criado_em),
        )
        certidao_id = cur.fetchone()["id"]
    conn.commit()
    return Certidao(
        id=certidao_id, cnpj_id=cnpj_id, orgao=orgao, numero=numero, emitida_em=emitida_em, valida_ate=valida_ate,
        arquivo_nome=arquivo_nome, criado_em=criado_em,
    )


def latest_certidoes_by_orgao(conn, cnpj_id: int) -> dict[str, Certidao]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM certidoes WHERE cnpj_id = %s ORDER BY orgao, valida_ate DESC", (cnpj_id,))
        rows = cur.fetchall()
    resultado: dict[str, Certidao] = {}
    for row in rows:
        if row["orgao"] not in resultado:
            resultado[row["orgao"]] = _row_to_certidao(row)
    return resultado


def get_certidao(conn, certidao_id: int) -> Certidao | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM certidoes WHERE id = %s", (certidao_id,))
        row = cur.fetchone()
    return _row_to_certidao(row) if row else None


def get_certidao_arquivo(conn, certidao_id: int) -> bytes | None:
    with conn.cursor() as cur:
        cur.execute("SELECT arquivo_conteudo FROM certidoes WHERE id = %s", (certidao_id,))
        row = cur.fetchone()
    return bytes(row["arquivo_conteudo"]) if row else None


def _row_to_certidao(row) -> Certidao:
    return Certidao(
        id=row["id"], cnpj_id=row["cnpj_id"], orgao=row["orgao"], numero=row["numero"],
        emitida_em=row["emitida_em"], valida_ate=row["valida_ate"], arquivo_nome=row["arquivo_nome"],
        criado_em=row["criado_em"],
    )


def upsert_dividas_abertas_pgfn(conn, registros: list[dict], base_referencia: str) -> int:
    agora = datetime.now(timezone.utc).isoformat()
    linhas = [
        (
            registro["numero_inscricao"],
            registro["cnpj"],
            registro["uf"],
            registro["receita_principal"],
            registro["situacao_inscricao"],
            registro["data_inscricao"],
            bool(registro["indicador_ajuizado"]),
            registro["valor_consolidado"],
            base_referencia,
            agora,
        )
        for registro in registros
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO pgfn_dividas_abertas
                (numero_inscricao, cnpj, uf, receita_principal, situacao_inscricao,
                 data_inscricao, indicador_ajuizado, valor_consolidado, base_referencia, importado_em)
            VALUES %s
            ON CONFLICT (numero_inscricao) DO UPDATE SET
                cnpj = excluded.cnpj,
                uf = excluded.uf,
                receita_principal = excluded.receita_principal,
                situacao_inscricao = excluded.situacao_inscricao,
                data_inscricao = excluded.data_inscricao,
                indicador_ajuizado = excluded.indicador_ajuizado,
                valor_consolidado = excluded.valor_consolidado,
                base_referencia = excluded.base_referencia,
                importado_em = excluded.importado_em
            """,
            linhas,
        )
    conn.commit()
    return len(registros)


def buscar_dados_abertos_por_inscricoes(conn, numeros: list[str]) -> dict[str, dict]:
    if not numeros:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT numero_inscricao, data_inscricao, situacao_inscricao, indicador_ajuizado "
            "FROM pgfn_dividas_abertas WHERE numero_inscricao = ANY(%s)",
            (numeros,),
        )
        rows = cur.fetchall()
    return {
        row["numero_inscricao"]: {
            "data_inscricao": row["data_inscricao"],
            "situacao_inscricao": row["situacao_inscricao"],
            "indicador_ajuizado": row["indicador_ajuizado"],
        }
        for row in rows
    }


def count_dividas_abertas_pgfn(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM pgfn_dividas_abertas")
        return cur.fetchone()["n"]
