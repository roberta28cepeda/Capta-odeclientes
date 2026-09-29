"""Backend Postgres — usado em produção quando alguma variável de conexão
está definida (mesmas do `fiscal_monitor`: `DATABASE_URL`, `POSTGRES_URL`,
`POSTGRES_URL_NON_POOLING`). Tabelas prefixadas com `campanha_` pra
conviver no mesmo banco Postgres do `fiscal_monitor` sem colidir nome.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

from src.campaigns.models import Envio, Evento, Lead, STATUS_ATIVO, Template
from src.campaigns.templates import DEFAULT_TEMPLATES

DEFAULT_DB_PATH = "output/campaigns.db"  # não usado neste backend; mantido por simetria de assinatura

SCHEMA = """
CREATE TABLE IF NOT EXISTS campanha_leads (
    id SERIAL PRIMARY KEY,
    cnpj TEXT NOT NULL UNIQUE,
    razao_social TEXT,
    email TEXT,
    status TEXT NOT NULL DEFAULT 'ativo',
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campanha_envios (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER NOT NULL REFERENCES campanha_leads(id),
    tipo TEXT NOT NULL,
    enviado_em TEXT NOT NULL,
    tracking_token TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS campanha_eventos (
    id SERIAL PRIMARY KEY,
    envio_id INTEGER NOT NULL REFERENCES campanha_envios(id),
    tipo TEXT NOT NULL,
    ocorrido_em TEXT NOT NULL,
    url TEXT
);

CREATE TABLE IF NOT EXISTS campanha_templates (
    tipo TEXT PRIMARY KEY,
    assunto TEXT NOT NULL,
    corpo TEXT NOT NULL,
    link_cta TEXT NOT NULL DEFAULT ''
);
"""

_CONNECTION_ENV_VARS = ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_URL_NON_POOLING")

# Mesmo cuidado do storage_postgres.py do fiscal_monitor: roda o DDL só uma
# vez por processo "quente", não em todo connect() (ALTER/CREATE pede lock).
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
            for tipo, template in DEFAULT_TEMPLATES.items():
                cur.execute(
                    "INSERT INTO campanha_templates (tipo, assunto, corpo, link_cta) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (tipo) DO NOTHING",
                    (tipo, template["assunto"], template["corpo"], template["link_cta"]),
                )
        conn.commit()
        _schema_ready = True
    return conn


def create_lead(conn, cnpj: str, razao_social: str | None = None, email: str | None = None) -> Lead:
    criado_em = datetime.now(timezone.utc).isoformat()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO campanha_leads (cnpj, razao_social, email, status, criado_em)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (cnpj) DO UPDATE SET
                razao_social = EXCLUDED.razao_social,
                email = COALESCE(campanha_leads.email, EXCLUDED.email)
            """,
            (cnpj, razao_social, email, STATUS_ATIVO, criado_em),
        )
    conn.commit()
    return get_lead_by_cnpj(conn, cnpj)  # type: ignore[return-value]


def get_lead(conn, lead_id: int) -> Lead | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM campanha_leads WHERE id = %s", (lead_id,))
        row = cur.fetchone()
    return _row_to_lead(row) if row else None


def get_lead_by_cnpj(conn, cnpj: str) -> Lead | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM campanha_leads WHERE cnpj = %s", (cnpj,))
        row = cur.fetchone()
    return _row_to_lead(row) if row else None


def list_leads(conn) -> list[Lead]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM campanha_leads ORDER BY id")
        rows = cur.fetchall()
    return [_row_to_lead(row) for row in rows]


def leads_sem_email(conn) -> list[Lead]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM campanha_leads WHERE status = 'ativo' AND (email IS NULL OR email = '') ORDER BY id"
        )
        rows = cur.fetchall()
    return [_row_to_lead(row) for row in rows]


def set_lead_email(conn, lead_id: int, email: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE campanha_leads SET email = %s WHERE id = %s", (email, lead_id))
    conn.commit()


def _row_to_lead(row) -> Lead:
    return Lead(
        id=row["id"], cnpj=row["cnpj"], razao_social=row["razao_social"], email=row["email"],
        status=row["status"], criado_em=row["criado_em"],
    )


def create_envio(conn, lead_id: int, tipo: str) -> Envio:
    enviado_em = datetime.now(timezone.utc).isoformat()
    tracking_token = secrets.token_urlsafe(16)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO campanha_envios (lead_id, tipo, enviado_em, tracking_token) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (lead_id, tipo, enviado_em, tracking_token),
        )
        envio_id = cur.fetchone()["id"]
    conn.commit()
    return Envio(id=envio_id, lead_id=lead_id, tipo=tipo, enviado_em=enviado_em, tracking_token=tracking_token)


def envios_do_lead(conn, lead_id: int) -> list[Envio]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM campanha_envios WHERE lead_id = %s ORDER BY id", (lead_id,))
        rows = cur.fetchall()
    return [_row_to_envio(row) for row in rows]


def get_envio_by_token(conn, tracking_token: str) -> Envio | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM campanha_envios WHERE tracking_token = %s", (tracking_token,))
        row = cur.fetchone()
    return _row_to_envio(row) if row else None


def envios_desde(conn, desde_iso: str) -> list[Envio]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM campanha_envios WHERE enviado_em >= %s ORDER BY id", (desde_iso,))
        rows = cur.fetchall()
    return [_row_to_envio(row) for row in rows]


def _row_to_envio(row) -> Envio:
    return Envio(
        id=row["id"], lead_id=row["lead_id"], tipo=row["tipo"], enviado_em=row["enviado_em"],
        tracking_token=row["tracking_token"],
    )


def add_evento(conn, envio_id: int, tipo: str, url: str | None = None) -> None:
    ocorrido_em = datetime.now(timezone.utc).isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO campanha_eventos (envio_id, tipo, ocorrido_em, url) VALUES (%s, %s, %s, %s)",
            (envio_id, tipo, ocorrido_em, url),
        )
    conn.commit()


def eventos_do_envio(conn, envio_id: int) -> list[Evento]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM campanha_eventos WHERE envio_id = %s ORDER BY id", (envio_id,))
        rows = cur.fetchall()
    return [_row_to_evento(row) for row in rows]


def eventos_desde(conn, desde_iso: str) -> list[Evento]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM campanha_eventos WHERE ocorrido_em >= %s ORDER BY id", (desde_iso,))
        rows = cur.fetchall()
    return [_row_to_evento(row) for row in rows]


def _row_to_evento(row) -> Evento:
    return Evento(id=row["id"], envio_id=row["envio_id"], tipo=row["tipo"], ocorrido_em=row["ocorrido_em"], url=row["url"])


def get_template(conn, tipo: str) -> Template | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM campanha_templates WHERE tipo = %s", (tipo,))
        row = cur.fetchone()
    return _row_to_template(row) if row else None


def list_templates(conn) -> list[Template]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM campanha_templates ORDER BY tipo")
        rows = cur.fetchall()
    return [_row_to_template(row) for row in rows]


def _row_to_template(row) -> Template:
    return Template(tipo=row["tipo"], assunto=row["assunto"], corpo=row["corpo"], link_cta=row["link_cta"])


def set_template(conn, tipo: str, assunto: str, corpo: str, link_cta: str = "") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO campanha_templates (tipo, assunto, corpo, link_cta) VALUES (%s, %s, %s, %s)
            ON CONFLICT (tipo) DO UPDATE SET assunto = EXCLUDED.assunto, corpo = EXCLUDED.corpo, link_cta = EXCLUDED.link_cta
            """,
            (tipo, assunto, corpo, link_cta),
        )
    conn.commit()
