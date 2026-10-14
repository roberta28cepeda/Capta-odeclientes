"""Backend SQLite — usado localmente (dev, testes, CLI) quando a env var
`DATABASE_URL` não está definida. Ver `storage.py` para o dispatcher e
`storage_postgres.py` para o backend de produção.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import date, datetime, timezone

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
    telefone TEXT,
    whatsapp_contatado_em TEXT,
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

CREATE TABLE IF NOT EXISTS campanha_notificacoes_diarias (
    tipo TEXT NOT NULL,
    data TEXT NOT NULL,
    enviado_em TEXT NOT NULL,
    PRIMARY KEY (tipo, data)
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


def bulk_create_leads(conn: sqlite3.Connection, tese: str, leads: list[dict]) -> int:
    """Importa vários leads de uma vez, numa única transação — usado pra
    listas grandes da PGFN (dezenas de milhares de linhas), onde criar um
    lead por vez (com commit a cada linha) seria lento demais e arriscaria
    estourar o tempo de execução da function serverless em produção.
    """
    criado_em = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        INSERT INTO campanha_leads (cnpj, tese, razao_social, email, status, criado_em, valor_divida)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cnpj, tese) DO UPDATE SET
            razao_social = excluded.razao_social,
            email = COALESCE(campanha_leads.email, excluded.email),
            valor_divida = COALESCE(excluded.valor_divida, campanha_leads.valor_divida)
        """,
        [
            (item["cnpj"], tese, item.get("razao_social"), item.get("email"), STATUS_ATIVO, criado_em, item.get("valor_divida"))
            for item in leads
        ],
    )
    conn.commit()
    return len(leads)


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


def leads_sem_telefone(conn: sqlite3.Connection, tese: str | None = None) -> list[Lead]:
    if tese is None:
        rows = conn.execute(
            "SELECT * FROM campanha_leads WHERE status = 'ativo' AND (telefone IS NULL OR telefone = '') ORDER BY id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM campanha_leads WHERE status = 'ativo' AND tese = ? AND (telefone IS NULL OR telefone = '') ORDER BY id",
            (tese,),
        ).fetchall()
    return [_row_to_lead(row) for row in rows]


def set_lead_telefone(conn: sqlite3.Connection, lead_id: int, telefone: str) -> None:
    conn.execute("UPDATE campanha_leads SET telefone = ? WHERE id = ?", (telefone, lead_id))
    conn.commit()


def leads_pendentes_whatsapp(conn: sqlite3.Connection) -> list[Lead]:
    """Leads com telefone já achado e ainda não marcados como contatados via
    WhatsApp — fila do "cartão" (`/admin/campanhas/whatsapp`), um por vez.
    """
    rows = conn.execute(
        """
        SELECT * FROM campanha_leads
        WHERE status = 'ativo' AND telefone IS NOT NULL AND telefone != '' AND whatsapp_contatado_em IS NULL
        ORDER BY id
        """
    ).fetchall()
    return [_row_to_lead(row) for row in rows]


def set_lead_whatsapp_contatado(conn: sqlite3.Connection, lead_id: int) -> None:
    contatado_em = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE campanha_leads SET whatsapp_contatado_em = ? WHERE id = ?", (contatado_em, lead_id))
    conn.commit()


def ja_notificado_hoje(conn: sqlite3.Connection, tipo: str, hoje: date | None = None) -> bool:
    """Evita duplicar um e-mail de notificação (resumo de WhatsApp,
    relatório semanal) quando o cron diário dispara mais de uma vez no
    mesmo dia — ver `marcar_notificado_hoje`."""
    data = (hoje or date.today()).isoformat()
    row = conn.execute(
        "SELECT 1 FROM campanha_notificacoes_diarias WHERE tipo = ? AND data = ?", (tipo, data)
    ).fetchone()
    return row is not None


def marcar_notificado_hoje(conn: sqlite3.Connection, tipo: str, hoje: date | None = None) -> None:
    data = (hoje or date.today()).isoformat()
    enviado_em = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO campanha_notificacoes_diarias (tipo, data, enviado_em) VALUES (?, ?, ?)",
        (tipo, data, enviado_em),
    )
    conn.commit()


def aparar_leads_por_tese(conn: sqlite3.Connection, tese: str, manter: int) -> int:
    """Mantém só os `manter` leads de maior valor_divida pra uma tese,
    apagando o resto — nunca remove um lead que já recebeu algum envio
    (preserva contato em andamento). Usado pra podar listas importadas
    grandes demais (ex: planilha bruta da PGFN) pro ritmo real de busca
    de e-mail/telefone e envio diário.
    """
    rows = conn.execute(
        "SELECT id, valor_divida FROM campanha_leads WHERE tese = ? "
        "AND id NOT IN (SELECT DISTINCT lead_id FROM campanha_envios)",
        (tese,),
    ).fetchall()
    ordenados = sorted(rows, key=lambda r: r["valor_divida"] if r["valor_divida"] is not None else -1.0, reverse=True)
    ids_para_apagar = [r["id"] for r in ordenados[manter:]]
    for i in range(0, len(ids_para_apagar), 500):
        lote = ids_para_apagar[i : i + 500]
        placeholders = ",".join("?" for _ in lote)
        conn.execute(f"DELETE FROM campanha_leads WHERE id IN ({placeholders})", lote)
    conn.commit()
    return len(ids_para_apagar)


def _row_to_lead(row: sqlite3.Row) -> Lead:
    return Lead(
        id=row["id"], cnpj=row["cnpj"], tese=row["tese"], razao_social=row["razao_social"], email=row["email"],
        status=row["status"], criado_em=row["criado_em"], valor_divida=row["valor_divida"],
        telefone=row["telefone"], whatsapp_contatado_em=row["whatsapp_contatado_em"],
    )


def create_envio(conn: sqlite3.Connection, lead_id: int, tipo: str, tracking_token: str | None = None) -> Envio:
    enviado_em = datetime.now(timezone.utc).isoformat()
    tracking_token = tracking_token or secrets.token_urlsafe(16)
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


def envios_por_lead_ids(conn: sqlite3.Connection, lead_ids: list[int]) -> dict[int, list[Envio]]:
    """Mesmo resultado que chamar `envios_do_lead` pra cada id, mas numa
    única consulta — evita N+1 query quando se precisa do histórico de
    envio de muitos leads de uma vez (ex: decidir quem está pendente hoje).
    """
    resultado: dict[int, list[Envio]] = {}
    if not lead_ids:
        return resultado
    placeholders = ",".join("?" * len(lead_ids))
    rows = conn.execute(
        f"SELECT * FROM campanha_envios WHERE lead_id IN ({placeholders}) ORDER BY lead_id, id", lead_ids
    ).fetchall()
    for row in rows:
        envio = _row_to_envio(row)
        resultado.setdefault(envio.lead_id, []).append(envio)
    return resultado


def get_envio_by_token(conn: sqlite3.Connection, tracking_token: str) -> Envio | None:
    row = conn.execute("SELECT * FROM campanha_envios WHERE tracking_token = ?", (tracking_token,)).fetchone()
    return _row_to_envio(row) if row else None


def envios_desde(conn: sqlite3.Connection, desde_iso: str) -> list[Envio]:
    rows = conn.execute(
        "SELECT * FROM campanha_envios WHERE enviado_em >= ? ORDER BY id", (desde_iso,)
    ).fetchall()
    return [_row_to_envio(row) for row in rows]


def deletar_envios_desde(conn: sqlite3.Connection, desde_iso: str) -> int:
    """Apaga todo envio registrado a partir de `desde_iso` — usado uma vez
    pra limpar os registros "fantasma" de dias em que um bug fazia o
    sistema marcar o lead como contatado mesmo quando o SMTP falhava (ver
    `enviar_para_lead`), sem nenhum e-mail sair de verdade. Nunca usada no
    fluxo normal; só via rota administrativa explícita."""
    cursor = conn.execute("DELETE FROM campanha_envios WHERE enviado_em >= ?", (desde_iso,))
    conn.commit()
    return cursor.rowcount


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


def metricas_por_tese(conn: sqlite3.Connection, hoje_iso: str, semana_iso: str) -> dict[str, dict]:
    """Painel da campanha — leads, envios e engajamento por tese, cada
    número numa consulta agregada (GROUP BY) própria, nunca um loop por
    lead/envio (mesmo problema de N+1 já corrigido na listagem de leads,
    só que aqui pra métrica agregada em vez de linha por linha)."""
    metricas: dict[str, dict] = {}

    def _tese(tese: str) -> dict:
        return metricas.setdefault(
            tese,
            {
                "leads": 0, "com_email": 0, "com_telefone": 0,
                "enviados_hoje": 0, "enviados_semana": 0,
                "aberturas": 0, "cliques": 0,
            },
        )

    for row in conn.execute(
        """
        SELECT tese, COUNT(*) AS leads,
               SUM(CASE WHEN email IS NOT NULL AND email != '' THEN 1 ELSE 0 END) AS com_email,
               SUM(CASE WHEN telefone IS NOT NULL AND telefone != '' THEN 1 ELSE 0 END) AS com_telefone
        FROM campanha_leads WHERE status = 'ativo' GROUP BY tese
        """
    ).fetchall():
        m = _tese(row["tese"])
        m["leads"], m["com_email"], m["com_telefone"] = row["leads"], row["com_email"], row["com_telefone"]

    for row in conn.execute(
        """
        SELECT l.tese AS tese,
               SUM(CASE WHEN e.enviado_em >= ? THEN 1 ELSE 0 END) AS hoje,
               SUM(CASE WHEN e.enviado_em >= ? THEN 1 ELSE 0 END) AS semana
        FROM campanha_envios e JOIN campanha_leads l ON l.id = e.lead_id
        GROUP BY l.tese
        """,
        (hoje_iso, semana_iso),
    ).fetchall():
        m = _tese(row["tese"])
        m["enviados_hoje"], m["enviados_semana"] = row["hoje"], row["semana"]

    for row in conn.execute(
        """
        SELECT l.tese AS tese, ev.tipo AS tipo, COUNT(DISTINCT ev.envio_id) AS total
        FROM campanha_eventos ev
        JOIN campanha_envios e ON e.id = ev.envio_id
        JOIN campanha_leads l ON l.id = e.lead_id
        GROUP BY l.tese, ev.tipo
        """
    ).fetchall():
        m = _tese(row["tese"])
        if row["tipo"] == "open":
            m["aberturas"] = row["total"]
        elif row["tipo"] == "click":
            m["cliques"] = row["total"]

    return metricas


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
