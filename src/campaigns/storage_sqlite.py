"""Backend SQLite — usado localmente (dev, testes, CLI) quando a env var
`DATABASE_URL` não está definida. Ver `storage.py` para o dispatcher e
`storage_postgres.py` para o backend de produção.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timezone

from src.campaigns.models import Envio, Evento, Lead, STATUS_ATIVO, Template
from src.campaigns.templates import DEFAULT_TEMPLATES

DEFAULT_DB_PATH = "output/campaigns.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS campanha_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj TEXT NOT NULL UNIQUE,
    razao_social TEXT,
    email TEXT,
    status TEXT NOT NULL DEFAULT 'ativo',
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campanha_envios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL REFERENCES campanha_leads(id),
    tipo TEXT NOT NULL,
    enviado_em TEXT NOT NULL,
    tracking_token TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS campanha_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    if db_path != ":memory:":
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _seed_default_templates(conn)
    return conn


def _seed_default_templates(conn: sqlite3.Connection) -> None:
    for tipo, template in DEFAULT_TEMPLATES.items():
        conn.execute(
            "INSERT OR IGNORE INTO campanha_templates (tipo, assunto, corpo, link_cta) VALUES (?, ?, ?, ?)",
            (tipo, template["assunto"], template["corpo"], template["link_cta"]),
        )
    conn.commit()


def create_lead(
    conn: sqlite3.Connection, cnpj: str, razao_social: str | None = None, email: str | None = None
) -> Lead:
    criado_em = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO campanha_leads (cnpj, razao_social, email, status, criado_em)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(cnpj) DO UPDATE SET
            razao_social = excluded.razao_social,
            email = COALESCE(campanha_leads.email, excluded.email)
        """,
        (cnpj, razao_social, email, STATUS_ATIVO, criado_em),
    )
    conn.commit()
    return get_lead_by_cnpj(conn, cnpj)  # type: ignore[return-value]


def get_lead(conn: sqlite3.Connection, lead_id: int) -> Lead | None:
    row = conn.execute("SELECT * FROM campanha_leads WHERE id = ?", (lead_id,)).fetchone()
    return _row_to_lead(row) if row else None


def get_lead_by_cnpj(conn: sqlite3.Connection, cnpj: str) -> Lead | None:
    row = conn.execute("SELECT * FROM campanha_leads WHERE cnpj = ?", (cnpj,)).fetchone()
    return _row_to_lead(row) if row else None


def list_leads(conn: sqlite3.Connection) -> list[Lead]:
    rows = conn.execute("SELECT * FROM campanha_leads ORDER BY id").fetchall()
    return [_row_to_lead(row) for row in rows]


def leads_sem_email(conn: sqlite3.Connection) -> list[Lead]:
    rows = conn.execute(
        "SELECT * FROM campanha_leads WHERE status = 'ativo' AND (email IS NULL OR email = '') ORDER BY id"
    ).fetchall()
    return [_row_to_lead(row) for row in rows]


def set_lead_email(conn: sqlite3.Connection, lead_id: int, email: str) -> None:
    conn.execute("UPDATE campanha_leads SET email = ? WHERE id = ?", (email, lead_id))
    conn.commit()


def _row_to_lead(row: sqlite3.Row) -> Lead:
    return Lead(
        id=row["id"],
        cnpj=row["cnpj"],
        razao_social=row["razao_social"],
        email=row["email"],
        status=row["status"],
        criado_em=row["criado_em"],
    )


def create_envio(conn: sqlite3.Connection, lead_id: int, tipo: str) -> Envio:
    enviado_em = datetime.now(timezone.utc).isoformat()
    tracking_token = secrets.token_urlsafe(16)
    cursor = conn.execute(
        "INSERT INTO campanha_envios (lead_id, tipo, enviado_em, tracking_token) VALUES (?, ?, ?, ?)",
        (lead_id, tipo, enviado_em, tracking_token),
    )
    conn.commit()
    return Envio(id=cursor.lastrowid, lead_id=lead_id, tipo=tipo, enviado_em=enviado_em, tracking_token=tracking_token)  # type: ignore[arg-type]


def envios_do_lead(conn: sqlite3.Connection, lead_id: int) -> list[Envio]:
    rows = conn.execute(
        "SELECT * FROM campanha_envios WHERE lead_id = ? ORDER BY id", (lead_id,)
    ).fetchall()
    return [_row_to_envio(row) for row in rows]


def get_envio_by_token(conn: sqlite3.Connection, tracking_token: str) -> Envio | None:
    row = conn.execute("SELECT * FROM campanha_envios WHERE tracking_token = ?", (tracking_token,)).fetchone()
    return _row_to_envio(row) if row else None


def envios_desde(conn: sqlite3.Connection, desde_iso: str) -> list[Envio]:
    rows = conn.execute(
        "SELECT * FROM campanha_envios WHERE enviado_em >= ? ORDER BY id", (desde_iso,)
    ).fetchall()
    return [_row_to_envio(row) for row in rows]


def _row_to_envio(row: sqlite3.Row) -> Envio:
    return Envio(
        id=row["id"], lead_id=row["lead_id"], tipo=row["tipo"], enviado_em=row["enviado_em"],
        tracking_token=row["tracking_token"],
    )


def add_evento(conn: sqlite3.Connection, envio_id: int, tipo: str, url: str | None = None) -> None:
    ocorrido_em = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO campanha_eventos (envio_id, tipo, ocorrido_em, url) VALUES (?, ?, ?, ?)",
        (envio_id, tipo, ocorrido_em, url),
    )
    conn.commit()


def eventos_do_envio(conn: sqlite3.Connection, envio_id: int) -> list[Evento]:
    rows = conn.execute(
        "SELECT * FROM campanha_eventos WHERE envio_id = ? ORDER BY id", (envio_id,)
    ).fetchall()
    return [_row_to_evento(row) for row in rows]


def eventos_desde(conn: sqlite3.Connection, desde_iso: str) -> list[Evento]:
    rows = conn.execute(
        "SELECT * FROM campanha_eventos WHERE ocorrido_em >= ? ORDER BY id", (desde_iso,)
    ).fetchall()
    return [_row_to_evento(row) for row in rows]


def _row_to_evento(row: sqlite3.Row) -> Evento:
    return Evento(id=row["id"], envio_id=row["envio_id"], tipo=row["tipo"], ocorrido_em=row["ocorrido_em"], url=row["url"])


def get_template(conn: sqlite3.Connection, tipo: str) -> Template | None:
    row = conn.execute("SELECT * FROM campanha_templates WHERE tipo = ?", (tipo,)).fetchone()
    return _row_to_template(row) if row else None


def list_templates(conn: sqlite3.Connection) -> list[Template]:
    rows = conn.execute("SELECT * FROM campanha_templates ORDER BY tipo").fetchall()
    return [_row_to_template(row) for row in rows]


def _row_to_template(row: sqlite3.Row) -> Template:
    return Template(tipo=row["tipo"], assunto=row["assunto"], corpo=row["corpo"], link_cta=row["link_cta"])


def set_template(conn: sqlite3.Connection, tipo: str, assunto: str, corpo: str, link_cta: str = "") -> None:
    conn.execute(
        """
        INSERT INTO campanha_templates (tipo, assunto, corpo, link_cta) VALUES (?, ?, ?, ?)
        ON CONFLICT(tipo) DO UPDATE SET assunto = excluded.assunto, corpo = excluded.corpo, link_cta = excluded.link_cta
        """,
        (tipo, assunto, corpo, link_cta),
    )
    conn.commit()
