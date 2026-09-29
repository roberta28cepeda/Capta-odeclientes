"""Dataclasses compartilhadas entre os dois backends de persistência
(`storage_sqlite.py` para dev/local, `storage_postgres.py` para produção).
"""

from __future__ import annotations

from dataclasses import dataclass

STATUS_ATIVO = "ativo"
STATUS_PAUSADO = "pausado"
STATUS_INVALIDO = "invalido"

TIPO_INICIAL = "inicial"
TIPOS_FOLLOWUP = ["followup_1", "followup_2", "followup_3"]
TIPOS_ENVIO = [TIPO_INICIAL, *TIPOS_FOLLOWUP]

DIAS_ENTRE_FOLLOWUPS = 3


@dataclass
class Lead:
    id: int
    cnpj: str
    razao_social: str | None
    email: str | None
    status: str
    criado_em: str


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
    tipo: str
    assunto: str
    corpo: str
    link_cta: str = ""
