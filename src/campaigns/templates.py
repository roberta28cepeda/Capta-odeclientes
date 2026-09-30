"""Templates de e-mail por tese — conteúdo real, transcrito dos HTMLs que
já rodavam no Apps Script (design + copy da Leactis), com o corpo agora
quebrado em campos estruturados (tag, título, parágrafos, checklist, CTA)
em vez de HTML bruto — mais fácil de editar pelo `/admin/campanhas/templates`
e evita duplicar ~8KB de HTML/logo por template salvo (ver `html_shell.py`).

Assuntos de e-mail (`assunto`) não existiam nos HTMLs originais (só o
corpo) — são um rascunho meu baseado no título de cada um, editável como
qualquer outro campo.

Placeholders aceitos em tag/headline/paragrafo1/paragrafo2/italico:
{{RAZAO_SOCIAL}}, {{CNPJ}}, {{VALOR_DIVIDA}} (só faz sentido pra quem usa).

Só o e-mail "inicial" de cada tese tem o texto definitivo (vindo do Apps
Script); o follow-up (único, 5 dias depois) é rascunho [AJUSTAR], porque
não existia como e-mail estruturado antes — no Apps Script real é texto
puro (sem HTML), reforçando o mesmo risco do e-mail inicial.
"""

from __future__ import annotations

from src.campaigns.models import TIPO_INICIAL, TIPOS_FOLLOWUP

_WHATSAPP_LINK = "https://wa.me/5521986956773"

_NOTAS_RODAPE_PADRAO = "dívida pequena resolvida cedo raramente vira problema grande depois."

_CHECKLIST_FOLLOWUP_PADRAO = [
    "[AJUSTAR] Motivo 1 pra responder agora",
    "[AJUSTAR] Motivo 2",
    "[AJUSTAR] Motivo 3",
    "[AJUSTAR] Motivo 4",
]


def _followup_rascunho(tag: str) -> dict:
    return {
        "assunto": "[RASCUNHO] Re: {{RAZAO_SOCIAL}}",
        "tag": tag,
        "headline": "[AJUSTAR] Título do follow-up (5 dias depois do inicial)",
        "paragrafo1": (
            "[AJUSTAR] Texto do follow-up pra {{RAZAO_SOCIAL}} — reforce o mesmo risco já mencionado no "
            "e-mail inicial. Este é só um rascunho, escreva o texto de verdade antes de ativar a tese."
        ),
        "paragrafo2": "[AJUSTAR] Segundo parágrafo, se precisar.",
        "checklist": list(_CHECKLIST_FOLLOWUP_PADRAO),
        "italico": "[AJUSTAR] Frase de urgência do follow-up.",
        "cta_texto": "QUERO RESOLVER ISSO AGORA",
        "link_cta": _WHATSAPP_LINK,
        "rodape_nota": _NOTAS_RODAPE_PADRAO,
    }


# {tese_slug: {tipo: {campos...}}}
DEFAULT_TEMPLATES: dict[str, dict[str, dict]] = {
    "transportadoras_pgfn": {
        TIPO_INICIAL: {
            "assunto": "{{RAZAO_SOCIAL}} — dívida com a PGFN ainda é pequena",
            "tag": "CONSULTA PÚBLICA, PGFN",
            "headline": "Essa dívida ainda é pequena. Sua empresa pode manter assim, ou deixar crescer.",
            "paragrafo1": (
                "A <strong>{{RAZAO_SOCIAL}}</strong> está na Lista de Devedores da União, com uma dívida de "
                "Simples Nacional de <strong style=\"color:#0c4a4a;\">R$ {{VALOR_DIVIDA}}</strong>. "
                "Dá pra resolver rápido, mas não pra sempre."
            ),
            "paragrafo2": (
                "Esse débito cresce todo mês com juros e multa, e pode fazer a Receita excluir a "
                "{{RAZAO_SOCIAL}} do Simples Nacional, trocando pra um regime bem mais caro justo na hora "
                "que menos dá pra bancar."
            ),
            "checklist": [
                "Resposta rápida, sem enrolação",
                "Diagnóstico gratuito, sem compromisso",
                "Você já sai sabendo qual é o caminho mais barato",
                "Zero burocracia pra você, a gente cuida da parte chata",
            ],
            "italico": "Cada mês parado é mais juro em cima do valor. Resolver agora é sempre mais barato que resolver depois.",
            "cta_texto": "QUERO RESOLVER ISSO AGORA",
            "link_cta": _WHATSAPP_LINK,
            "rodape_nota": "dívida pequena resolvida cedo raramente vira problema grande depois.",
        },
        TIPOS_FOLLOWUP[0]: _followup_rascunho("CONSULTA PÚBLICA, PGFN"),
    },
    "simples_ibs_cbs": {
        TIPO_INICIAL: {
            "assunto": "{{RAZAO_SOCIAL}} — sem CND, sua empresa fica travada",
            "tag": "SITUAÇÃO FISCAL, SIMPLES NACIONAL",
            "headline": "Sem CND, sua empresa não fecha contrato, não tira habite-se, não participa de licitação.",
            "paragrafo1": (
                "A <strong>{{RAZAO_SOCIAL}}</strong> está com uma pendência no Simples Nacional. Sem isso "
                "resolvido, sua empresa fica sem Certidão Negativa de Débitos (trava habite-se, averbação de "
                "obra, financiamento e licitação) e corre risco real de sair do regime."
            ),
            "paragrafo2": (
                "E o prazo está correndo: até 30 de setembro, toda empresa do Simples decide o futuro "
                "tributário dela pra 2027. Com pendência aberta, sua empresa pode nem chegar nessa escolha."
            ),
            "checklist": [
                "Diagnóstico da pendência em até 48h",
                "Plano pra recuperar sua CND",
                "Simulação do melhor regime pra 2027",
                "Acompanhamento até o fim do prazo (30/09)",
            ],
            "italico": "Cada dia sem resolver é um dia sem CND, e um dia mais perto de setembro fechar sem sua empresa ter decidido nada.",
            "cta_texto": "QUERO RESOLVER ISSO E ENTENDER O MELHOR REGIME",
            "link_cta": _WHATSAPP_LINK,
            "rodape_nota": (
                "essa data foi antecipada especialmente por causa da Reforma Tributária, é diferente do "
                "prazo de janeiro que valia até agora. Muita empresa e até muito contador ainda não "
                "perceberam essa mudança."
            ),
        },
        TIPOS_FOLLOWUP[0]: _followup_rascunho("SITUAÇÃO FISCAL, SIMPLES NACIONAL"),
    },
    "industria_ibs_cbs": {
        TIPO_INICIAL: {
            "assunto": "{{RAZAO_SOCIAL}} — concorrente pode oferecer mais crédito que você",
            "tag": "SITUAÇÃO FISCAL, SIMPLES NACIONAL",
            "headline": "Seu concorrente pode oferecer mais crédito pro mesmo cliente que compra de você.",
            "paragrafo1": (
                "A <strong>{{RAZAO_SOCIAL}}</strong> está com uma pendência no Simples Nacional. Sem isso "
                "resolvido, sua empresa fica sem CND (trava financiamento, contrato maior e licitação) e "
                "corre risco real de sair do regime."
            ),
            "paragrafo2": (
                "E até 30 de setembro fica pior: sua indústria decide como vai gerar crédito pros clientes a "
                "partir de 2027. Decidir errado, ou nem chegar a decidir por causa da pendência, pode custar "
                "contrato pra concorrente que oferece mais crédito."
            ),
            "checklist": [
                "Diagnóstico da pendência em até 48h",
                "Plano pra recuperar sua CND",
                "Simulação de crédito pros seus clientes B2B",
                "Acompanhamento até o fim do prazo (30/09)",
            ],
            "italico": "Cada dia sem resolver é um dia mais perto de perder contrato pra concorrente, e um dia mais perto de setembro fechar sem sua indústria ter decidido nada.",
            "cta_texto": "QUERO RESOLVER ISSO E GANHAR COMPETITIVIDADE",
            "link_cta": _WHATSAPP_LINK,
            "rodape_nota": (
                "essa data foi antecipada especialmente por causa da Reforma Tributária, é diferente do "
                "prazo de janeiro que valia até agora. Muita empresa e até muito contador ainda não "
                "perceberam essa mudança."
            ),
        },
        TIPOS_FOLLOWUP[0]: _followup_rascunho("SITUAÇÃO FISCAL, SIMPLES NACIONAL"),
    },
    "contadores_certificado": {
        TIPO_INICIAL: {
            "assunto": "Todo certificado que seu cliente emite sem você é dinheiro na mesa",
            "tag": "EXCLUSIVO PARA ESCRITÓRIOS CONTÁBEIS",
            "headline": 'Todo certificado que seu cliente emite sem você é <span style="color:#7ff5e3;">dinheiro na mesa</span>.',
            "paragrafo1": (
                "Toda semana algum cliente pede pro seu escritório uma indicação de onde emitir o "
                "<strong style=\"color:#0c4a4a;\">certificado digital</strong>. Hoje, esse pedido vira "
                "trabalho, e o retorno financeiro fica todo com outra empresa."
            ),
            "paragrafo2": (
                "Com a <strong style=\"color:#0c4a4a;\">Leactis</strong>, essa mesma indicação, que você já "
                "faz de graça hoje, passa a gerar margem direto pra você: <strong style=\"color:#0c4a4a;\">"
                "você define o preço</strong> cobrado do cliente, paga um valor fixo de "
                "<strong style=\"color:#0c4a4a;\">R$ 120 à Leactis</strong> por certificado emitido, e fica "
                "com a diferença."
            ),
            "checklist": [
                "Você define o preço ao cliente, e fica com a margem",
                "Repasse em até 72h, ou consolidado todo dia 12",
                "Emissão e suporte inteiramente pela Leactis",
                "Sem estrutura técnica nem equipe nova",
            ],
            "italico": "Para manter o suporte próximo, aceitamos poucos parceiros por região: garanta a sua vaga antes que o cupo da sua área feche.",
            "cta_texto": "QUERO COMEÇAR A GANHAR COM MINHAS INDICAÇÕES",
            "link_cta": _WHATSAPP_LINK,
            "rodape_nota": _NOTAS_RODAPE_PADRAO,
        },
        TIPOS_FOLLOWUP[0]: _followup_rascunho("EXCLUSIVO PARA ESCRITÓRIOS CONTÁBEIS"),
    },
    "contadores_tributaria": {
        TIPO_INICIAL: {
            "assunto": "Cliente seu pode ter direito a reaver tributo da Reforma",
            "tag": "PARCERIA EXCLUSIVA PARA ESCRITÓRIOS CONTÁBEIS",
            "headline": "Cliente seu pode ter direito a reaver tributo da Reforma, e isso pode virar ganho seu, não só dele.",
            "paragrafo1": (
                "Cliente seu no <strong style=\"color:#0c4a4a;\">Simples Nacional</strong> ou "
                "<strong style=\"color:#0c4a4a;\">Lucro Presumido</strong> pode ter sido afetado pelas "
                "mudanças da Reforma Tributária, com fundamento jurídico real pra revisão. Hoje, identificar "
                "isso não rende nada extra pro seu escritório."
            ),
            "paragrafo2": (
                "A <strong style=\"color:#0c4a4a;\">Leactis</strong> trabalha junto com um escritório de "
                "advocacia tributária especializado. Quando a análise de um cliente seu indicar espaço pra "
                "revisão jurídica, você indica, a gente cuida da parte legal, e o "
                "<strong style=\"color:#0c4a4a;\">bônus por indicação</strong> é seu."
            ),
            "checklist": [
                "Bônus por indicação em cada caso encaminhado",
                "Você continua sendo o consultor de confiança do cliente",
                "Análise inicial sem custo pro seu escritório",
                "Sem exclusividade, sem burocracia pra começar",
            ],
            "italico": "Para manter o suporte próximo, aceitamos poucos parceiros por região: garanta a sua vaga antes que o cupo da sua área feche.",
            "cta_texto": "QUERO SER PARCEIRO LEACTIS",
            "link_cta": _WHATSAPP_LINK,
            "rodape_nota": _NOTAS_RODAPE_PADRAO,
        },
        TIPOS_FOLLOWUP[0]: _followup_rascunho("PARCERIA EXCLUSIVA PARA ESCRITÓRIOS CONTÁBEIS"),
    },
    "mei_regularizacao": {
        TIPO_INICIAL: {
            "assunto": "[RASCUNHO] {{RAZAO_SOCIAL}} — regularização do MEI",
            "tag": "REGULARIZAÇÃO MEI",
            "headline": "[AJUSTAR: título da tese de regularização de MEI — ainda não recebi o texto/ângulo dessa tese.]",
            "paragrafo1": "[AJUSTAR] Texto sobre a situação do MEI {{RAZAO_SOCIAL}} — preciso que você me passe o ângulo/pitch dessa tese (ex: pendência específica, prazo, isenção perdida etc.) pra escrever de verdade.",
            "paragrafo2": "[AJUSTAR] Segundo parágrafo.",
            "checklist": list(_CHECKLIST_FOLLOWUP_PADRAO),
            "italico": "[AJUSTAR] Frase de urgência.",
            "cta_texto": "QUERO REGULARIZAR MEU MEI",
            "link_cta": _WHATSAPP_LINK,
            "rodape_nota": _NOTAS_RODAPE_PADRAO,
        },
        TIPOS_FOLLOWUP[0]: _followup_rascunho("REGULARIZAÇÃO MEI"),
    },
    "industria_tributaria_geral": {
        TIPO_INICIAL: {
            "assunto": "[RASCUNHO] {{RAZAO_SOCIAL}} — débito tributário federal",
            "tag": "DÍVIDA ATIVA DA UNIÃO",
            "headline": "[AJUSTAR: título da tese de dívida tributária geral (Demais débitos - Tributários) — ainda não recebi o ângulo/pitch.]",
            "paragrafo1": (
                "[AJUSTAR] Texto sobre o débito tributário federal da {{RAZAO_SOCIAL}} — preciso do "
                "ângulo/pitch pra escrever de verdade. Atenção: essa lista é de \"Demais débitos - "
                "Tributários\", não Simples Nacional — são empresas de porte maior, não use a copy da "
                "tese industria_ibs_cbs (que fala de Simples Nacional) aqui."
            ),
            "paragrafo2": "[AJUSTAR] Segundo parágrafo.",
            "checklist": list(_CHECKLIST_FOLLOWUP_PADRAO),
            "italico": "[AJUSTAR] Frase de urgência.",
            "cta_texto": "QUERO RESOLVER ISSO",
            "link_cta": _WHATSAPP_LINK,
            "rodape_nota": _NOTAS_RODAPE_PADRAO,
        },
        TIPOS_FOLLOWUP[0]: _followup_rascunho("DÍVIDA ATIVA DA UNIÃO"),
    },
}
