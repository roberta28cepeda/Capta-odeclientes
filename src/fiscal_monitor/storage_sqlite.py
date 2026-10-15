"""Backend SQLite — usado localmente (dev, testes, CLI) quando a env var
`DATABASE_URL` não está definida. Ver `storage.py` para o dispatcher e
`storage_postgres.py` para o backend de produção.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timezone

from src.fiscal_monitor.models import (
    AdminUser,
    AuditoriaEvento,
    Certidao,
    Cnpj,
    CobrancaAsaas,
    Documento,
    Finding,
    Honorario,
    Obrigacao,
    OportunidadeCredito,
    PAPEL_PADRAO,
    SolicitacaoAssinatura,
    Tenant,
)

DEFAULT_DB_PATH = "output/fiscal_monitor.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    contato_whatsapp TEXT,
    plano TEXT,
    criado_em TEXT NOT NULL,
    acesso_token TEXT NOT NULL DEFAULT '',
    contato_email TEXT,
    cnpj TEXT
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

CREATE TABLE IF NOT EXISTS obrigacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_id INTEGER NOT NULL REFERENCES cnpjs(id),
    tipo TEXT NOT NULL,
    vencimento TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendente'
);

CREATE TABLE IF NOT EXISTS certidoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_id INTEGER NOT NULL REFERENCES cnpjs(id),
    orgao TEXT NOT NULL,
    numero TEXT,
    emitida_em TEXT NOT NULL,
    valida_ate TEXT NOT NULL,
    arquivo_nome TEXT NOT NULL,
    arquivo_conteudo BLOB NOT NULL,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nome TEXT,
    criado_em TEXT NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1,
    papel TEXT NOT NULL DEFAULT 'operador'
);

CREATE TABLE IF NOT EXISTS pgfn_dividas_abertas (
    numero_inscricao TEXT PRIMARY KEY,
    cnpj TEXT NOT NULL,
    uf TEXT,
    receita_principal TEXT,
    situacao_inscricao TEXT NOT NULL,
    data_inscricao TEXT,
    indicador_ajuizado INTEGER NOT NULL DEFAULT 0,
    valor_consolidado REAL,
    base_referencia TEXT NOT NULL,
    importado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS pgfn_dividas_abertas_cnpj_idx ON pgfn_dividas_abertas(cnpj);

CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_id INTEGER NOT NULL REFERENCES cnpjs(id),
    tipo TEXT NOT NULL,
    nome_arquivo TEXT NOT NULL,
    arquivo_conteudo BLOB NOT NULL,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS solicitacoes_assinatura (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    documento_id INTEGER NOT NULL REFERENCES documentos(id),
    provider_envelope_id TEXT NOT NULL,
    signatario_nome TEXT NOT NULL,
    signatario_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'enviado',
    documento_assinado_id INTEGER REFERENCES documentos(id),
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oportunidades_credito (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj_id INTEGER NOT NULL REFERENCES cnpjs(id),
    tipo TEXT NOT NULL,
    descricao TEXT NOT NULL,
    valor_estimado REAL,
    status TEXT NOT NULL DEFAULT 'identificada',
    evidencia TEXT,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS honorarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    competencia TEXT NOT NULL,
    valor REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendente',
    vencimento TEXT NOT NULL,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cobrancas_asaas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    honorario_id INTEGER NOT NULL UNIQUE REFERENCES honorarios(id),
    asaas_customer_id TEXT NOT NULL,
    asaas_payment_id TEXT NOT NULL,
    invoice_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendente',
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auditoria_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quem TEXT NOT NULL,
    acao TEXT NOT NULL,
    entidade TEXT NOT NULL,
    entidade_id INTEGER,
    detalhes TEXT,
    criado_em TEXT NOT NULL
);
"""


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    if db_path != ":memory:":
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
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

    try:
        conn.execute("ALTER TABLE tenants ADD COLUMN acesso_token TEXT NOT NULL DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # coluna já existe

    try:
        conn.execute("ALTER TABLE tenants ADD COLUMN contato_email TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # coluna já existe

    try:
        conn.execute("ALTER TABLE cnpjs ADD COLUMN uf TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # coluna já existe

    # Bancos antigos ganham token vazio pela migração acima — gera um de verdade
    # pra cada tenant que ainda não tem, senão o dono fica trancado pra fora.
    rows = conn.execute("SELECT id FROM tenants WHERE acesso_token = ''").fetchall()
    for row in rows:
        conn.execute("UPDATE tenants SET acesso_token = ? WHERE id = ?", (secrets.token_urlsafe(24), row["id"]))
    if rows:
        conn.commit()


def create_tenant(
    conn: sqlite3.Connection,
    nome: str,
    contato_whatsapp: str | None = None,
    plano: str | None = None,
    contato_email: str | None = None,
    cnpj: str | None = None,
) -> Tenant:
    criado_em = datetime.now(timezone.utc).isoformat()
    acesso_token = secrets.token_urlsafe(24)
    cursor = conn.execute(
        """
        INSERT INTO tenants (nome, contato_whatsapp, plano, criado_em, acesso_token, contato_email, cnpj)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (nome, contato_whatsapp, plano, criado_em, acesso_token, contato_email, cnpj),
    )
    conn.commit()
    return Tenant(
        id=cursor.lastrowid,
        nome=nome,
        contato_whatsapp=contato_whatsapp,
        plano=plano,
        criado_em=criado_em,
        acesso_token=acesso_token,
        contato_email=contato_email,
        cnpj=cnpj,
    )


def get_tenant(conn: sqlite3.Connection, tenant_id: int) -> Tenant | None:
    row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    return _row_to_tenant(row) if row else None


def list_tenants(conn: sqlite3.Connection) -> list[Tenant]:
    rows = conn.execute("SELECT * FROM tenants ORDER BY id").fetchall()
    return [_row_to_tenant(row) for row in rows]


def set_tenant_cnpj(conn: sqlite3.Connection, tenant_id: int, cnpj: str) -> None:
    conn.execute("UPDATE tenants SET cnpj = ? WHERE id = ?", (cnpj, tenant_id))
    conn.commit()


def _row_to_tenant(row: sqlite3.Row) -> Tenant:
    return Tenant(
        id=row["id"],
        nome=row["nome"],
        contato_whatsapp=row["contato_whatsapp"],
        plano=row["plano"],
        criado_em=row["criado_em"],
        acesso_token=row["acesso_token"],
        contato_email=row["contato_email"],
        cnpj=row["cnpj"] if "cnpj" in row.keys() else None,
    )


def upsert_cnpj(
    conn: sqlite3.Connection,
    tenant_id: int,
    cnpj: str,
    razao_social: str | None = None,
    nome_fantasia: str | None = None,
    regime_tributario: str | None = None,
    uf: str | None = None,
) -> Cnpj:
    conn.execute(
        """
        INSERT INTO cnpjs (tenant_id, cnpj, razao_social, nome_fantasia, ativo, regime_tributario, uf)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(tenant_id, cnpj) DO UPDATE SET
            razao_social = excluded.razao_social,
            nome_fantasia = excluded.nome_fantasia,
            regime_tributario = excluded.regime_tributario,
            uf = COALESCE(excluded.uf, cnpjs.uf)
        """,
        (tenant_id, cnpj, razao_social, nome_fantasia, regime_tributario, uf),
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
        uf=row["uf"],
    )


def create_obrigacao(conn: sqlite3.Connection, cnpj_id: int, tipo: str, vencimento: str) -> Obrigacao:
    cursor = conn.execute(
        "INSERT INTO obrigacoes (cnpj_id, tipo, vencimento, status) VALUES (?, ?, ?, 'pendente')",
        (cnpj_id, tipo, vencimento),
    )
    conn.commit()
    return Obrigacao(id=cursor.lastrowid, cnpj_id=cnpj_id, tipo=tipo, vencimento=vencimento, status="pendente")  # type: ignore[arg-type]


def list_obrigacoes(conn: sqlite3.Connection, cnpj_id: int) -> list[Obrigacao]:
    rows = conn.execute(
        "SELECT * FROM obrigacoes WHERE cnpj_id = ? ORDER BY vencimento", (cnpj_id,)
    ).fetchall()
    return [_row_to_obrigacao(row) for row in rows]


def marcar_obrigacao_entregue(conn: sqlite3.Connection, obrigacao_id: int) -> None:
    conn.execute("UPDATE obrigacoes SET status = 'entregue' WHERE id = ?", (obrigacao_id,))
    conn.commit()


def get_obrigacao(conn: sqlite3.Connection, obrigacao_id: int) -> Obrigacao | None:
    row = conn.execute("SELECT * FROM obrigacoes WHERE id = ?", (obrigacao_id,)).fetchone()
    return _row_to_obrigacao(row) if row else None


def _row_to_obrigacao(row: sqlite3.Row) -> Obrigacao:
    return Obrigacao(id=row["id"], cnpj_id=row["cnpj_id"], tipo=row["tipo"], vencimento=row["vencimento"], status=row["status"])


def create_certidao(
    conn: sqlite3.Connection, cnpj_id: int, orgao: str, numero: str | None, emitida_em: str, valida_ate: str,
    arquivo_nome: str, arquivo_conteudo: bytes,
) -> Certidao:
    criado_em = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO certidoes (cnpj_id, orgao, numero, emitida_em, valida_ate, arquivo_nome, arquivo_conteudo, criado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cnpj_id, orgao, numero, emitida_em, valida_ate, arquivo_nome, arquivo_conteudo, criado_em),
    )
    conn.commit()
    return Certidao(
        id=cursor.lastrowid, cnpj_id=cnpj_id, orgao=orgao, numero=numero, emitida_em=emitida_em,  # type: ignore[arg-type]
        valida_ate=valida_ate, arquivo_nome=arquivo_nome, criado_em=criado_em,
    )


def latest_certidoes_by_orgao(conn: sqlite3.Connection, cnpj_id: int) -> dict[str, Certidao]:
    """A certidão mais recente (maior `valida_ate`) de cada órgão daquele CNPJ."""
    rows = conn.execute(
        "SELECT * FROM certidoes WHERE cnpj_id = ? ORDER BY orgao, valida_ate DESC", (cnpj_id,)
    ).fetchall()
    resultado: dict[str, Certidao] = {}
    for row in rows:
        if row["orgao"] not in resultado:
            resultado[row["orgao"]] = _row_to_certidao(row)
    return resultado


def get_certidao(conn: sqlite3.Connection, certidao_id: int) -> Certidao | None:
    row = conn.execute("SELECT * FROM certidoes WHERE id = ?", (certidao_id,)).fetchone()
    return _row_to_certidao(row) if row else None


def get_certidao_arquivo(conn: sqlite3.Connection, certidao_id: int) -> bytes | None:
    row = conn.execute("SELECT arquivo_conteudo FROM certidoes WHERE id = ?", (certidao_id,)).fetchone()
    return row["arquivo_conteudo"] if row else None


def _row_to_certidao(row: sqlite3.Row) -> Certidao:
    return Certidao(
        id=row["id"], cnpj_id=row["cnpj_id"], orgao=row["orgao"], numero=row["numero"],
        emitida_em=row["emitida_em"], valida_ate=row["valida_ate"], arquivo_nome=row["arquivo_nome"],
        criado_em=row["criado_em"],
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


def create_admin_user(
    conn: sqlite3.Connection, username: str, password_hash: str, nome: str | None = None, papel: str = PAPEL_PADRAO
) -> AdminUser:
    criado_em = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO admin_users (username, password_hash, nome, criado_em, ativo, papel) VALUES (?, ?, ?, ?, 1, ?)",
        (username, password_hash, nome, criado_em, papel),
    )
    conn.commit()
    return AdminUser(
        id=cursor.lastrowid, username=username, password_hash=password_hash, nome=nome,  # type: ignore[arg-type]
        criado_em=criado_em, ativo=True, papel=papel,
    )


def get_admin_user_by_username(conn: sqlite3.Connection, username: str) -> AdminUser | None:
    row = conn.execute("SELECT * FROM admin_users WHERE username = ?", (username,)).fetchone()
    return _row_to_admin_user(row) if row else None


def list_admin_users(conn: sqlite3.Connection) -> list[AdminUser]:
    rows = conn.execute("SELECT * FROM admin_users ORDER BY id").fetchall()
    return [_row_to_admin_user(row) for row in rows]


def set_admin_user_ativo(conn: sqlite3.Connection, user_id: int, ativo: bool) -> None:
    conn.execute("UPDATE admin_users SET ativo = ? WHERE id = ?", (int(ativo), user_id))
    conn.commit()


def set_admin_user_papel(conn: sqlite3.Connection, user_id: int, papel: str) -> None:
    conn.execute("UPDATE admin_users SET papel = ? WHERE id = ?", (papel, user_id))
    conn.commit()


def _row_to_admin_user(row: sqlite3.Row) -> AdminUser:
    return AdminUser(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        nome=row["nome"],
        criado_em=row["criado_em"],
        ativo=bool(row["ativo"]),
        papel=row["papel"] if "papel" in row.keys() else PAPEL_PADRAO,
    )


def upsert_dividas_abertas_pgfn(conn: sqlite3.Connection, registros: list[dict], base_referencia: str) -> int:
    agora = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        INSERT INTO pgfn_dividas_abertas
            (numero_inscricao, cnpj, uf, receita_principal, situacao_inscricao,
             data_inscricao, indicador_ajuizado, valor_consolidado, base_referencia, importado_em)
        VALUES (:numero_inscricao, :cnpj, :uf, :receita_principal, :situacao_inscricao,
                :data_inscricao, :indicador_ajuizado, :valor_consolidado, :base_referencia, :importado_em)
        ON CONFLICT(numero_inscricao) DO UPDATE SET
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
        [
            {
                **registro,
                "indicador_ajuizado": int(registro["indicador_ajuizado"]),
                "base_referencia": base_referencia,
                "importado_em": agora,
            }
            for registro in registros
        ],
    )
    conn.commit()
    return len(registros)


def buscar_dados_abertos_por_inscricoes(conn: sqlite3.Connection, numeros: list[str]) -> dict[str, dict]:
    if not numeros:
        return {}
    placeholders = ",".join("?" for _ in numeros)
    rows = conn.execute(
        "SELECT numero_inscricao, data_inscricao, situacao_inscricao, indicador_ajuizado "
        f"FROM pgfn_dividas_abertas WHERE numero_inscricao IN ({placeholders})",
        numeros,
    ).fetchall()
    return {
        row["numero_inscricao"]: {
            "data_inscricao": row["data_inscricao"],
            "situacao_inscricao": row["situacao_inscricao"],
            "indicador_ajuizado": bool(row["indicador_ajuizado"]),
        }
        for row in rows
    }


def count_dividas_abertas_pgfn(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM pgfn_dividas_abertas").fetchone()["n"]


def create_documento(
    conn: sqlite3.Connection, cnpj_id: int, tipo: str, nome_arquivo: str, arquivo_conteudo: bytes,
) -> Documento:
    criado_em = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO documentos (cnpj_id, tipo, nome_arquivo, arquivo_conteudo, criado_em) VALUES (?, ?, ?, ?, ?)",
        (cnpj_id, tipo, nome_arquivo, arquivo_conteudo, criado_em),
    )
    conn.commit()
    return Documento(id=cursor.lastrowid, cnpj_id=cnpj_id, tipo=tipo, nome_arquivo=nome_arquivo, criado_em=criado_em)  # type: ignore[arg-type]


def list_documentos(conn: sqlite3.Connection, cnpj_id: int) -> list[Documento]:
    rows = conn.execute(
        "SELECT id, cnpj_id, tipo, nome_arquivo, criado_em FROM documentos WHERE cnpj_id = ? ORDER BY id DESC",
        (cnpj_id,),
    ).fetchall()
    return [_row_to_documento(row) for row in rows]


def get_documento(conn: sqlite3.Connection, documento_id: int) -> Documento | None:
    row = conn.execute(
        "SELECT id, cnpj_id, tipo, nome_arquivo, criado_em FROM documentos WHERE id = ?", (documento_id,)
    ).fetchone()
    return _row_to_documento(row) if row else None


def get_documento_arquivo(conn: sqlite3.Connection, documento_id: int) -> bytes | None:
    row = conn.execute("SELECT arquivo_conteudo FROM documentos WHERE id = ?", (documento_id,)).fetchone()
    return bytes(row["arquivo_conteudo"]) if row else None


def _row_to_documento(row: sqlite3.Row) -> Documento:
    return Documento(
        id=row["id"], cnpj_id=row["cnpj_id"], tipo=row["tipo"], nome_arquivo=row["nome_arquivo"],
        criado_em=row["criado_em"],
    )


def create_solicitacao_assinatura(
    conn: sqlite3.Connection, documento_id: int, provider_envelope_id: str, signatario_nome: str,
    signatario_email: str,
) -> SolicitacaoAssinatura:
    agora = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO solicitacoes_assinatura
            (documento_id, provider_envelope_id, signatario_nome, signatario_email, status, criado_em, atualizado_em)
        VALUES (?, ?, ?, ?, 'enviado', ?, ?)
        """,
        (documento_id, provider_envelope_id, signatario_nome, signatario_email, agora, agora),
    )
    conn.commit()
    return SolicitacaoAssinatura(
        id=cursor.lastrowid, documento_id=documento_id, provider_envelope_id=provider_envelope_id,  # type: ignore[arg-type]
        signatario_nome=signatario_nome, signatario_email=signatario_email, status="enviado",
        documento_assinado_id=None, criado_em=agora, atualizado_em=agora,
    )


def list_solicitacoes_assinatura(conn: sqlite3.Connection, documento_id: int) -> list[SolicitacaoAssinatura]:
    rows = conn.execute(
        "SELECT * FROM solicitacoes_assinatura WHERE documento_id = ? ORDER BY id DESC", (documento_id,)
    ).fetchall()
    return [_row_to_solicitacao_assinatura(row) for row in rows]


def get_solicitacao_assinatura_by_envelope(
    conn: sqlite3.Connection, provider_envelope_id: str
) -> SolicitacaoAssinatura | None:
    row = conn.execute(
        "SELECT * FROM solicitacoes_assinatura WHERE provider_envelope_id = ?", (provider_envelope_id,)
    ).fetchone()
    return _row_to_solicitacao_assinatura(row) if row else None


def set_solicitacao_assinatura_status(
    conn: sqlite3.Connection, solicitacao_id: int, status: str, documento_assinado_id: int | None = None
) -> None:
    conn.execute(
        "UPDATE solicitacoes_assinatura SET status = ?, documento_assinado_id = ?, atualizado_em = ? WHERE id = ?",
        (status, documento_assinado_id, datetime.now(timezone.utc).isoformat(), solicitacao_id),
    )
    conn.commit()


def _row_to_solicitacao_assinatura(row: sqlite3.Row) -> SolicitacaoAssinatura:
    return SolicitacaoAssinatura(
        id=row["id"], documento_id=row["documento_id"], provider_envelope_id=row["provider_envelope_id"],
        signatario_nome=row["signatario_nome"], signatario_email=row["signatario_email"], status=row["status"],
        documento_assinado_id=row["documento_assinado_id"], criado_em=row["criado_em"],
        atualizado_em=row["atualizado_em"],
    )


def create_oportunidade_credito(
    conn: sqlite3.Connection, cnpj_id: int, tipo: str, descricao: str, valor_estimado: float | None = None,
    evidencia: str | None = None,
) -> OportunidadeCredito:
    criado_em = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO oportunidades_credito (cnpj_id, tipo, descricao, valor_estimado, status, evidencia, criado_em)
        VALUES (?, ?, ?, ?, 'identificada', ?, ?)
        """,
        (cnpj_id, tipo, descricao, valor_estimado, evidencia, criado_em),
    )
    conn.commit()
    return OportunidadeCredito(
        id=cursor.lastrowid, cnpj_id=cnpj_id, tipo=tipo, descricao=descricao, valor_estimado=valor_estimado,  # type: ignore[arg-type]
        status="identificada", evidencia=evidencia, criado_em=criado_em,
    )


def list_oportunidades_credito(conn: sqlite3.Connection, cnpj_id: int) -> list[OportunidadeCredito]:
    rows = conn.execute(
        "SELECT * FROM oportunidades_credito WHERE cnpj_id = ? ORDER BY id DESC", (cnpj_id,)
    ).fetchall()
    return [_row_to_oportunidade_credito(row) for row in rows]


def set_oportunidade_credito_status(conn: sqlite3.Connection, oportunidade_id: int, status: str) -> None:
    conn.execute("UPDATE oportunidades_credito SET status = ? WHERE id = ?", (status, oportunidade_id))
    conn.commit()


def _row_to_oportunidade_credito(row: sqlite3.Row) -> OportunidadeCredito:
    return OportunidadeCredito(
        id=row["id"], cnpj_id=row["cnpj_id"], tipo=row["tipo"], descricao=row["descricao"],
        valor_estimado=row["valor_estimado"], status=row["status"], evidencia=row["evidencia"],
        criado_em=row["criado_em"],
    )


def create_honorario(conn: sqlite3.Connection, tenant_id: int, competencia: str, valor: float, vencimento: str) -> Honorario:
    criado_em = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO honorarios (tenant_id, competencia, valor, status, vencimento, criado_em)
        VALUES (?, ?, ?, 'pendente', ?, ?)
        """,
        (tenant_id, competencia, valor, vencimento, criado_em),
    )
    conn.commit()
    return Honorario(
        id=cursor.lastrowid, tenant_id=tenant_id, competencia=competencia, valor=valor, status="pendente",  # type: ignore[arg-type]
        vencimento=vencimento, criado_em=criado_em,
    )


def list_honorarios(conn: sqlite3.Connection, tenant_id: int) -> list[Honorario]:
    rows = conn.execute(
        "SELECT * FROM honorarios WHERE tenant_id = ? ORDER BY competencia DESC", (tenant_id,)
    ).fetchall()
    return [_row_to_honorario(row) for row in rows]


def set_honorario_status(conn: sqlite3.Connection, honorario_id: int, status: str) -> None:
    conn.execute("UPDATE honorarios SET status = ? WHERE id = ?", (status, honorario_id))
    conn.commit()


def honorarios_pendentes_resumo(conn: sqlite3.Connection) -> dict:
    """Agregado pra `/admin/status` — total pendente/atrasado em todos os
    tenants, numa consulta só (sem loop por tenant)."""
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'pendente' THEN valor ELSE 0 END) AS total_pendente,
            SUM(CASE WHEN status = 'atrasado' THEN valor ELSE 0 END) AS total_atrasado,
            SUM(CASE WHEN status = 'pendente' THEN 1 ELSE 0 END) AS qtd_pendente,
            SUM(CASE WHEN status = 'atrasado' THEN 1 ELSE 0 END) AS qtd_atrasado
        FROM honorarios
        """
    ).fetchone()
    return {
        "total_pendente": row["total_pendente"] or 0.0,
        "total_atrasado": row["total_atrasado"] or 0.0,
        "qtd_pendente": row["qtd_pendente"] or 0,
        "qtd_atrasado": row["qtd_atrasado"] or 0,
    }


def _row_to_honorario(row: sqlite3.Row) -> Honorario:
    return Honorario(
        id=row["id"], tenant_id=row["tenant_id"], competencia=row["competencia"], valor=row["valor"],
        status=row["status"], vencimento=row["vencimento"], criado_em=row["criado_em"],
    )


def create_cobranca_asaas(
    conn: sqlite3.Connection, honorario_id: int, asaas_customer_id: str, asaas_payment_id: str, invoice_url: str,
) -> CobrancaAsaas:
    agora = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO cobrancas_asaas
            (honorario_id, asaas_customer_id, asaas_payment_id, invoice_url, status, criado_em, atualizado_em)
        VALUES (?, ?, ?, ?, 'pendente', ?, ?)
        """,
        (honorario_id, asaas_customer_id, asaas_payment_id, invoice_url, agora, agora),
    )
    conn.commit()
    return CobrancaAsaas(
        id=cursor.lastrowid, honorario_id=honorario_id, asaas_customer_id=asaas_customer_id,  # type: ignore[arg-type]
        asaas_payment_id=asaas_payment_id, invoice_url=invoice_url, status="pendente",
        criado_em=agora, atualizado_em=agora,
    )


def get_cobranca_asaas_by_honorario(conn: sqlite3.Connection, honorario_id: int) -> CobrancaAsaas | None:
    row = conn.execute("SELECT * FROM cobrancas_asaas WHERE honorario_id = ?", (honorario_id,)).fetchone()
    return _row_to_cobranca_asaas(row) if row else None


def get_cobranca_asaas_by_payment_id(conn: sqlite3.Connection, asaas_payment_id: str) -> CobrancaAsaas | None:
    row = conn.execute("SELECT * FROM cobrancas_asaas WHERE asaas_payment_id = ?", (asaas_payment_id,)).fetchone()
    return _row_to_cobranca_asaas(row) if row else None


def set_cobranca_asaas_status(conn: sqlite3.Connection, cobranca_id: int, status: str) -> None:
    conn.execute(
        "UPDATE cobrancas_asaas SET status = ?, atualizado_em = ? WHERE id = ?",
        (status, datetime.now(timezone.utc).isoformat(), cobranca_id),
    )
    conn.commit()


def _row_to_cobranca_asaas(row: sqlite3.Row) -> CobrancaAsaas:
    return CobrancaAsaas(
        id=row["id"], honorario_id=row["honorario_id"], asaas_customer_id=row["asaas_customer_id"],
        asaas_payment_id=row["asaas_payment_id"], invoice_url=row["invoice_url"], status=row["status"],
        criado_em=row["criado_em"], atualizado_em=row["atualizado_em"],
    )


def registrar_auditoria(
    conn: sqlite3.Connection, quem: str, acao: str, entidade: str, entidade_id: int | None = None,
    detalhes: str | None = None,
) -> None:
    criado_em = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO auditoria_eventos (quem, acao, entidade, entidade_id, detalhes, criado_em) VALUES (?, ?, ?, ?, ?, ?)",
        (quem, acao, entidade, entidade_id, detalhes, criado_em),
    )
    conn.commit()


def list_auditoria(conn: sqlite3.Connection, limite: int = 200) -> list[AuditoriaEvento]:
    rows = conn.execute(
        "SELECT * FROM auditoria_eventos ORDER BY id DESC LIMIT ?", (limite,)
    ).fetchall()
    return [_row_to_auditoria(row) for row in rows]


def _row_to_auditoria(row: sqlite3.Row) -> AuditoriaEvento:
    return AuditoriaEvento(
        id=row["id"], quem=row["quem"], acao=row["acao"], entidade=row["entidade"],
        entidade_id=row["entidade_id"], detalhes=row["detalhes"], criado_em=row["criado_em"],
    )
