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

_CHECKLIST_SEPARADOR = "\n"

SCHEMA = """
CREATE TABLE IF NOT EXISTS campanha_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj TEXT NOT NULL,
    tese TEXT NOT NULL,
    razao_social TEXT,
    email TEXT,
    status TEXT NOT NULL DEFAULT 'ativo',
    criado_em TEXT NOT NULL,
    valor_divida REAL,
    UNIQUE(cnpj, tese)
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
    tese TEXT NOT NULL,
    tipo TEXT NOT NULL,
    assunto TEXT NOT NULL,
    tag TEXT NOT NULL DEFAULT '',
    headline TEXT NOT NULL DEFAULT '',
    paragrafo1 TEXT NOT NULL DEFAULT '',
    paragrafo2 TEXT NOT NULL DEFAULT '',
    checklist TEXT NOT NULL DEFAULT '',
    italico TEXT NOT NULL DEFAULT '',
    cta_texto TEXT NOT NULL DEFAULT '',
    link_cta TEXT NOT NULL DEFAULT '',
    rodape_nota TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (tese, tipo)
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
    for tese, templates_do_tese in DEFAULT_TEMPLATES.items():
        for tipo, campos in templates_do_tese.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO campanha_templates
                    (tese, tipo, assunto, tag, headline, paragrafo1, paragrafo2, checklist, italico, cta_texto, link_cta, rodape_nota)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tese, tipo, campos["assunto"], campos["tag"], campos["headline"], campos["paragrafo1"],
                    campos["paragrafo2"], _CHECKLIST_SEPARADOR.join(campos["checklist"]), campos["italico"],
                    campos["cta_texto"], campos["link_cta"], campos["rodape_nota"],
                ),
            )
    conn.commit()


def create_lead(
    conn: sqlite3.Connection, cnpj: str, tese: str, razao_social: str | None = None, email: str | None = None,
    valor_divida: float | None = None,
) -> Lead:
    criado_em = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO campanha_leads (cnpj, tese, razao_social, email, status, criado_em, valor_divida)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cnpj, tese) DO UPDATE SET
            razao_social = excluded.razao_social,
            email = COALESCE(campanha_leads.email, excluded.email),
            valor_divida = COALESCE(excluded.valor_divida, campanha_leads.valor_divida)
        """,
        (cnpj, tese, razao_social, email, STATUS_ATIVO, criado_em, valor_divida),
    )
    conn.commit()
    return get_lead_by_cnpj(conn, cnpj, tese)  # type: ignore[return-value]


def get_lead(conn: sqlite3.Connection, lead_id: int) -> Lead | None:
    row = conn.execute("SELECT * FROM campanha_leads WHERE id = ?", (lead_id,)).fetchone()
    return _row_to_lead(row) if row else None


def get_lead_by_cnpj(conn: sqlite3.Connection, cnpj: str, tese: str) -> Lead | None:
    row = conn.execute("SELECT * FROM campanha_leads WHERE cnpj = ? AND tese = ?", (cnpj, tese)).fetchone()
    return _row_to_lead(row) if row else None


def list_leads(conn: sqlite3.Connection, tese: str | None = None) -> list[Lead]:
    if tese is None:
        rows = conn.execute("SELECT * FROM campanha_leads ORDER BY id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM campanha_leads WHERE tese = ? ORDER BY id", (tese,)).fetchall()
    return [_row_to_lead(row) for row in rows]


def list_teses(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT tese FROM campanha_leads ORDER BY tese").fetchall()
    return [row["tese"] for row in rows]


def leads_sem_email(conn: sqlite3.Connection, tese: str | None = None) -> list[Lead]:
    if tese is None:
        rows = conn.execute(
            "SELECT * FROM campanha_leads WHERE status = 'ativo' AND (email IS NULL OR email = '') ORDER BY id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM campanha_leads WHERE status = 'ativo' AND tese = ? AND (email IS NULL OR email = '') ORDER BY id",
            (tese,),
        ).fetchall()
    return [_row_to_lead(row) for row in rows]


def set_lead_email(conn: sqlite3.Connection, lead_id: int, email: str) -> None:
    conn.execute("UPDATE campanha_leads SET email = ? WHERE id = ?", (email, lead_id))
    conn.commit()


def _row_to_lead(row: sqlite3.Row) -> Lead:
    return Lead(
        id=row["id"], cnpj=row["cnpj"], tese=row["tese"], razao_social=row["razao_social"], email=row["email"],
        status=row["status"], criado_em=row["criado_em"], valor_divida=row["valor_divida"],
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


def envios_de_hoje_por_tese(conn: sqlite3.Connection, tese: str, desde_iso: str) -> int:
    """Quantos envios (inicial + follow-up somados) já saíram hoje pra essa
    tese — usado pra aplicar o limite diário por tese.
    """
    row = conn.execute(
        """
        SELECT COUNT(*) AS total FROM campanha_envios
        JOIN campanha_leads ON campanha_leads.id = campanha_envios.lead_id
        WHERE campanha_leads.tese = ? AND campanha_envios.enviado_em >= ?
        """,
        (tese, desde_iso),
    ).fetchone()
    return row["total"]


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


def get_template(conn: sqlite3.Connection, tese: str, tipo: str) -> Template | None:
    row = conn.execute("SELECT * FROM campanha_templates WHERE tese = ? AND tipo = ?", (tese, tipo)).fetchone()
    return _row_to_template(row) if row else None


def list_templates(conn: sqlite3.Connection, tese: str | None = None) -> list[Template]:
    if tese is None:
        rows = conn.execute("SELECT * FROM campanha_templates ORDER BY tese, tipo").fetchall()
    else:
        rows = conn.execute("SELECT * FROM campanha_templates WHERE tese = ? ORDER BY tipo", (tese,)).fetchall()
    return [_row_to_template(row) for row in rows]


def list_template_teses(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT tese FROM campanha_templates ORDER BY tese").fetchall()
    return [row["tese"] for row in rows]


def _row_to_template(row: sqlite3.Row) -> Template:
    return Template(
        tese=row["tese"], tipo=row["tipo"], assunto=row["assunto"], tag=row["tag"], headline=row["headline"],
        paragrafo1=row["paragrafo1"], paragrafo2=row["paragrafo2"],
        checklist=row["checklist"].split(_CHECKLIST_SEPARADOR) if row["checklist"] else [],
        italico=row["italico"], cta_texto=row["cta_texto"], link_cta=row["link_cta"], rodape_nota=row["rodape_nota"],
    )


def set_template(
    conn: sqlite3.Connection, tese: str, tipo: str, assunto: str, tag: str, headline: str, paragrafo1: str,
    paragrafo2: str, checklist: list[str], italico: str, cta_texto: str, link_cta: str, rodape_nota: str,
) -> None:
    conn.execute(
        """
        INSERT INTO campanha_templates
            (tese, tipo, assunto, tag, headline, paragrafo1, paragrafo2, checklist, italico, cta_texto, link_cta, rodape_nota)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tese, tipo) DO UPDATE SET
            assunto = excluded.assunto, tag = excluded.tag, headline = excluded.headline,
            paragrafo1 = excluded.paragrafo1, paragrafo2 = excluded.paragrafo2, checklist = excluded.checklist,
            italico = excluded.italico, cta_texto = excluded.cta_texto, link_cta = excluded.link_cta,
            rodape_nota = excluded.rodape_nota
        """,
        (
            tese, tipo, assunto, tag, headline, paragrafo1, paragrafo2, _CHECKLIST_SEPARADOR.join(checklist),
            italico, cta_texto, link_cta, rodape_nota,
        ),
    )
    conn.commit()
