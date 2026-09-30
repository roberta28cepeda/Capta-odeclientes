"""Backend Postgres — usado em produção quando alguma variável de conexão
está definida (mesmas do `fiscal_monitor` — os dois módulos dividem o
mesmo banco Postgres, em tabelas com prefixo diferente). Tabelas de leads
e templates são por tese (ver `models.py`).
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

_CHECKLIST_SEPARADOR = "\n"

SCHEMA = """
CREATE TABLE IF NOT EXISTS campanha_leads (
    id SERIAL PRIMARY KEY,
    cnpj TEXT NOT NULL,
    tese TEXT NOT NULL,
    razao_social TEXT,
    email TEXT,
    status TEXT NOT NULL DEFAULT 'ativo',
    criado_em TEXT NOT NULL,
    valor_divida DOUBLE PRECISION,
    UNIQUE(cnpj, tese)
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
            # Migração da versão anterior (leads únicos só por cnpj, templates só por tipo,
            # sem os campos estruturados novos) — banco já existente no ar antes desta mudança.
            cur.execute("ALTER TABLE campanha_leads ADD COLUMN IF NOT EXISTS tese TEXT NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE campanha_leads ADD COLUMN IF NOT EXISTS valor_divida DOUBLE PRECISION")
            cur.execute("DELETE FROM campanha_leads WHERE tese = ''")
            cur.execute("ALTER TABLE campanha_leads DROP CONSTRAINT IF EXISTS campanha_leads_cnpj_key")
            cur.execute("ALTER TABLE campanha_leads DROP CONSTRAINT IF EXISTS campanha_leads_cnpj_tese_key")
            cur.execute("ALTER TABLE campanha_leads ADD CONSTRAINT campanha_leads_cnpj_tese_key UNIQUE (cnpj, tese)")
            for coluna, tipo_sql in [
                ("tese", "TEXT NOT NULL DEFAULT ''"), ("tag", "TEXT NOT NULL DEFAULT ''"),
                ("headline", "TEXT NOT NULL DEFAULT ''"), ("paragrafo1", "TEXT NOT NULL DEFAULT ''"),
                ("paragrafo2", "TEXT NOT NULL DEFAULT ''"), ("checklist", "TEXT NOT NULL DEFAULT ''"),
                ("italico", "TEXT NOT NULL DEFAULT ''"), ("cta_texto", "TEXT NOT NULL DEFAULT ''"),
                ("rodape_nota", "TEXT NOT NULL DEFAULT ''"),
            ]:
                cur.execute(f"ALTER TABLE campanha_templates ADD COLUMN IF NOT EXISTS {coluna} {tipo_sql}")
            cur.execute("DELETE FROM campanha_templates WHERE tese = ''")
            cur.execute("ALTER TABLE campanha_templates DROP CONSTRAINT IF EXISTS campanha_templates_pkey")
            cur.execute("ALTER TABLE campanha_templates ADD PRIMARY KEY (tese, tipo)")
            # Coluna da versão anterior (HTML bruto), substituída pelos campos estruturados acima.
            cur.execute("ALTER TABLE campanha_templates DROP COLUMN IF EXISTS corpo")

            for tese, templates_do_tese in DEFAULT_TEMPLATES.items():
                for tipo, campos in templates_do_tese.items():
                    cur.execute(
                        """
                        INSERT INTO campanha_templates
                            (tese, tipo, assunto, tag, headline, paragrafo1, paragrafo2, checklist, italico, cta_texto, link_cta, rodape_nota)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tese, tipo) DO NOTHING
                        """,
                        (
                            tese, tipo, campos["assunto"], campos["tag"], campos["headline"], campos["paragrafo1"],
                            campos["paragrafo2"], _CHECKLIST_SEPARADOR.join(campos["checklist"]), campos["italico"],
                            campos["cta_texto"], campos["link_cta"], campos["rodape_nota"],
                        ),
                    )
        conn.commit()
        _schema_ready = True
    return conn


def create_lead(
    conn, cnpj: str, tese: str, razao_social: str | None = None, email: str | None = None,
    valor_divida: float | None = None,
) -> Lead:
    criado_em = datetime.now(timezone.utc).isoformat()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO campanha_leads (cnpj, tese, razao_social, email, status, criado_em, valor_divida)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (cnpj, tese) DO UPDATE SET
                razao_social = EXCLUDED.razao_social,
                email = COALESCE(campanha_leads.email, EXCLUDED.email),
                valor_divida = COALESCE(EXCLUDED.valor_divida, campanha_leads.valor_divida)
            """,
            (cnpj, tese, razao_social, email, STATUS_ATIVO, criado_em, valor_divida),
        )
    conn.commit()
    return get_lead_by_cnpj(conn, cnpj, tese)  # type: ignore[return-value]


def get_lead(conn, lead_id: int) -> Lead | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM campanha_leads WHERE id = %s", (lead_id,))
        row = cur.fetchone()
    return _row_to_lead(row) if row else None


def get_lead_by_cnpj(conn, cnpj: str, tese: str) -> Lead | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM campanha_leads WHERE cnpj = %s AND tese = %s", (cnpj, tese))
        row = cur.fetchone()
    return _row_to_lead(row) if row else None


def list_leads(conn, tese: str | None = None) -> list[Lead]:
    with conn.cursor() as cur:
        if tese is None:
            cur.execute("SELECT * FROM campanha_leads ORDER BY id")
        else:
            cur.execute("SELECT * FROM campanha_leads WHERE tese = %s ORDER BY id", (tese,))
        rows = cur.fetchall()
    return [_row_to_lead(row) for row in rows]


def list_teses(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT tese FROM campanha_leads ORDER BY tese")
        rows = cur.fetchall()
    return [row["tese"] for row in rows]


def leads_sem_email(conn, tese: str | None = None) -> list[Lead]:
    with conn.cursor() as cur:
        if tese is None:
            cur.execute("SELECT * FROM campanha_leads WHERE status = 'ativo' AND (email IS NULL OR email = '') ORDER BY id")
        else:
            cur.execute(
                "SELECT * FROM campanha_leads WHERE status = 'ativo' AND tese = %s AND (email IS NULL OR email = '') ORDER BY id",
                (tese,),
            )
        rows = cur.fetchall()
    return [_row_to_lead(row) for row in rows]


def set_lead_email(conn, lead_id: int, email: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE campanha_leads SET email = %s WHERE id = %s", (email, lead_id))
    conn.commit()


def _row_to_lead(row) -> Lead:
    return Lead(
        id=row["id"], cnpj=row["cnpj"], tese=row["tese"], razao_social=row["razao_social"], email=row["email"],
        status=row["status"], criado_em=row["criado_em"], valor_divida=row["valor_divida"],
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


def envios_de_hoje_por_tese(conn, tese: str, desde_iso: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS total FROM campanha_envios
            JOIN campanha_leads ON campanha_leads.id = campanha_envios.lead_id
            WHERE campanha_leads.tese = %s AND campanha_envios.enviado_em >= %s
            """,
            (tese, desde_iso),
        )
        row = cur.fetchone()
    return row["total"]


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


def get_template(conn, tese: str, tipo: str) -> Template | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM campanha_templates WHERE tese = %s AND tipo = %s", (tese, tipo))
        row = cur.fetchone()
    return _row_to_template(row) if row else None


def list_templates(conn, tese: str | None = None) -> list[Template]:
    with conn.cursor() as cur:
        if tese is None:
            cur.execute("SELECT * FROM campanha_templates ORDER BY tese, tipo")
        else:
            cur.execute("SELECT * FROM campanha_templates WHERE tese = %s ORDER BY tipo", (tese,))
        rows = cur.fetchall()
    return [_row_to_template(row) for row in rows]


def list_template_teses(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT tese FROM campanha_templates ORDER BY tese")
        rows = cur.fetchall()
    return [row["tese"] for row in rows]


def _row_to_template(row) -> Template:
    return Template(
        tese=row["tese"], tipo=row["tipo"], assunto=row["assunto"], tag=row["tag"], headline=row["headline"],
        paragrafo1=row["paragrafo1"], paragrafo2=row["paragrafo2"],
        checklist=row["checklist"].split(_CHECKLIST_SEPARADOR) if row["checklist"] else [],
        italico=row["italico"], cta_texto=row["cta_texto"], link_cta=row["link_cta"], rodape_nota=row["rodape_nota"],
    )


def set_template(
    conn, tese: str, tipo: str, assunto: str, tag: str, headline: str, paragrafo1: str, paragrafo2: str,
    checklist: list[str], italico: str, cta_texto: str, link_cta: str, rodape_nota: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO campanha_templates
                (tese, tipo, assunto, tag, headline, paragrafo1, paragrafo2, checklist, italico, cta_texto, link_cta, rodape_nota)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tese, tipo) DO UPDATE SET
                assunto = EXCLUDED.assunto, tag = EXCLUDED.tag, headline = EXCLUDED.headline,
                paragrafo1 = EXCLUDED.paragrafo1, paragrafo2 = EXCLUDED.paragrafo2, checklist = EXCLUDED.checklist,
                italico = EXCLUDED.italico, cta_texto = EXCLUDED.cta_texto, link_cta = EXCLUDED.link_cta,
                rodape_nota = EXCLUDED.rodape_nota
            """,
            (
                tese, tipo, assunto, tag, headline, paragrafo1, paragrafo2, _CHECKLIST_SEPARADOR.join(checklist),
                italico, cta_texto, link_cta, rodape_nota,
            ),
        )
    conn.commit()
