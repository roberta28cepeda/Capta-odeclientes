"""Dataclasses compartilhadas entre os dois backends de persistência
(`storage_sqlite.py` para dev/local, `storage_postgres.py` para produção) —
mesmo formato de dado, independente de onde está guardado.
"""

from __future__ import annotations

from dataclasses import dataclass

REGIMES_TRIBUTARIOS = {"mei", "simples", "presumido", "real"}


@dataclass
class Tenant:
    id: int
    nome: str
    contato_whatsapp: str | None
    plano: str | None
    criado_em: str
    acesso_token: str = ""
    contato_email: str | None = None


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
