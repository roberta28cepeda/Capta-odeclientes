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
    uf: str | None = None


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


@dataclass
class Obrigacao:
    """Obrigação fiscal recorrente de um CNPJ (ex: DAS, DCTFWeb, DEFIS), com
    prazo e status — diferente de `Finding` (achado/pendência descoberta via
    CSV importado): aqui é uma rotina esperada, não um problema encontrado.
    """

    id: int
    cnpj_id: int
    tipo: str
    vencimento: str
    status: str  # "pendente" ou "entregue"


ORGAOS_CERTIDAO = {"federal", "sp", "rj"}


@dataclass
class Certidao:
    """Metadados da certidão (PDF real, enviado pelo escritório) de um
    órgão (federal/sp/rj) de um CNPJ — o conteúdo do arquivo fica à parte
    (`storage.get_certidao_arquivo`), pra não carregar o PDF inteiro toda
    vez que só a lista é exibida.
    """

    id: int
    cnpj_id: int
    orgao: str
    numero: str | None
    emitida_em: str
    valida_ate: str
    arquivo_nome: str
    criado_em: str


@dataclass
class AdminUser:
    """Conta individual de acesso ao painel de admin (login por pessoa da
    equipe, além do usuário/senha "mestre" em ADMIN_USERNAME/ADMIN_PASSWORD).
    """

    id: int
    username: str
    password_hash: str
    nome: str | None
    criado_em: str
    ativo: bool = True
