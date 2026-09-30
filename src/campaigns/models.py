"""Dataclasses compartilhadas entre os dois backends de persistência
(`storage_sqlite.py` para dev/local, `storage_postgres.py` para produção).

Uma "tese" é um ângulo/público de campanha (ex: transportadoras com dívida
PGFN, escritórios contábeis pra parceria de certificado digital) — cada
tese tem sua própria planilha/lista de leads e sua própria sequência de
e-mails (`Template` por tipo), mas todas compartilham o mesmo mecanismo de
envio/follow-up/rastreio.
"""

from __future__ import annotations

from dataclasses import dataclass

STATUS_ATIVO = "ativo"
STATUS_PAUSADO = "pausado"
STATUS_INVALIDO = "invalido"

TIPO_INICIAL = "inicial"
# Um único follow-up, 5 dias depois do inicial — mesma cadência do Apps
# Script já em produção (nunca foram 3 follow-ups por lá).
TIPOS_FOLLOWUP = ["followup_1"]
TIPOS_ENVIO = [TIPO_INICIAL, *TIPOS_FOLLOWUP]

DIAS_ENTRE_FOLLOWUPS = 5

# Total de e-mails (inicial + follow-up somados) que uma tese pode mandar
# por dia — mesmo limite que o Apps Script já usava, pra não estourar
# reputação de envio nem parecer disparo em massa.
LIMITE_ENVIOS_POR_TESE_POR_DIA = 10


@dataclass
class Lead:
    id: int
    cnpj: str
    tese: str
    razao_social: str | None
    email: str | None
    status: str
    criado_em: str
    valor_divida: float | None = None
    telefone: str | None = None
    whatsapp_contatado_em: str | None = None


@dataclass
class Envio:
    id: int
    lead_id: int
    tipo: str
    enviado_em: str
    tracking_token: str


@dataclass
class Evento:
    id: int
    envio_id: int
    tipo: str  # "open" ou "click"
    ocorrido_em: str
    url: str | None


@dataclass
class Template:
    tese: str
    tipo: str
    assunto: str
    tag: str
    headline: str
    paragrafo1: str
    paragrafo2: str
    checklist: list[str]
    italico: str
    cta_texto: str
    link_cta: str
    rodape_nota: str
