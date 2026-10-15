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
    cnpj: str | None = None  # CNPJ do próprio escritório — necessário pra gerar cobrança na Asaas (cpfCnpj)


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


PAPEIS_ADMIN = ["leitor", "operador", "gestor"]
PAPEL_PADRAO = "operador"


@dataclass
class AdminUser:
    """Conta individual de acesso ao painel de admin (login por pessoa da
    equipe, além do usuário/senha "mestre" em ADMIN_USERNAME/ADMIN_PASSWORD).

    `papel` é a permissão gravada no banco (leitor < operador < gestor) —
    o login mestre não tem papel gravado, é sempre o teto implícito
    (ver `src/common/webauth.py`).
    """

    id: int
    username: str
    password_hash: str
    nome: str | None
    criado_em: str
    ativo: bool = True
    papel: str = PAPEL_PADRAO


TIPOS_DOCUMENTO = {"contrato", "procuracao", "xml", "outro"}


@dataclass
class Documento:
    """Repositório documental genérico por CNPJ (contrato, procuração, XML,
    outros) — mesmo padrão de `Certidao` (metadado separado do conteúdo,
    que fica em `arquivo_conteudo`/BYTEA, pra não carregar o arquivo
    inteiro toda vez que só a lista é exibida).
    """

    id: int
    cnpj_id: int
    tipo: str
    nome_arquivo: str
    criado_em: str


TIPOS_DOCUMENTO_ASSINAVEIS = {"contrato", "procuracao"}
STATUS_ASSINATURA = ["enviado", "aguardando_assinatura", "assinado", "recusado", "cancelado"]


@dataclass
class SolicitacaoAssinatura:
    """Solicitação de assinatura eletrônica (via Clicksign) de um
    `Documento` já enviado — entidade separada, não altera `documentos`.
    Quando `status == "assinado"`, `documento_assinado_id` aponta pro
    NOVO `Documento` criado com o PDF assinado (preserva as duas
    versões em vez de sobrescrever).
    """

    id: int
    documento_id: int
    provider_envelope_id: str
    signatario_nome: str
    signatario_email: str
    status: str
    documento_assinado_id: int | None
    criado_em: str
    atualizado_em: str


TIPOS_OPORTUNIDADE_CREDITO = {
    "simples_monofasico_das",
    "pis_cofins_nao_cumulativos",
    "icms_st",
    "irpj_csll_retidos",
    "previdenciario_iss_ipi",
}
STATUS_OPORTUNIDADE_CREDITO = ["identificada", "em_analise", "validada", "protocolada", "recebida"]


@dataclass
class OportunidadeCredito:
    """Registro MANUAL de uma oportunidade de crédito tributário
    identificada por fora do sistema (ex: pelo contador, analisando XML/
    EFD) — não é detecção automática, o Capta não tem motor de auditoria
    tributária. Só dá um lugar estruturado pra guardar e acompanhar o que
    já foi achado, com evidência e status, por CNPJ.
    """

    id: int
    cnpj_id: int
    tipo: str
    descricao: str
    valor_estimado: float | None
    status: str
    evidencia: str | None
    criado_em: str


STATUS_HONORARIO = ["pendente", "pago", "atrasado"]


@dataclass
class Honorario:
    """Cobrança de honorário mensal de um tenant — registro de controle
    (competência/valor/status); o gateway de pagamento (Asaas) é opcional,
    ver `CobrancaAsaas` abaixo — sem ele, o status continua marcado à mão.
    """

    id: int
    tenant_id: int
    competencia: str  # "AAAA-MM"
    valor: float
    status: str
    vencimento: str
    criado_em: str


STATUS_COBRANCA_ASAAS = ["pendente", "confirmado", "recebido", "atrasado", "cancelado"]


@dataclass
class CobrancaAsaas:
    """Cobrança real gerada na Asaas (boleto/PIX/cartão) pra um
    `Honorario` — entidade separada, 1:1 (não altera `honorarios`); o
    status aqui é espelhado pro `Honorario.status` via webhook."""

    id: int
    honorario_id: int
    asaas_customer_id: str
    asaas_payment_id: str
    invoice_url: str
    status: str
    criado_em: str
    atualizado_em: str


@dataclass
class AuditoriaEvento:
    """Linha da trilha de auditoria — quem fez o quê, quando, em qual
    entidade. Cobre só as ações novas desta fase (conversão de lead em
    cliente, oportunidade de crédito, honorário, documento); não tenta
    cobrir retroativamente o sistema inteiro.
    """

    id: int
    quem: str
    acao: str
    entidade: str
    entidade_id: int | None
    detalhes: str | None
    criado_em: str
