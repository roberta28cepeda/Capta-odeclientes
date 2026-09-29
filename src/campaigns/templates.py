"""Textos padrão dos e-mails da campanha — rascunho genérico, pra ser
ajustado depois via `/admin/campanhas/templates` ou `--editar-template`
no CLI (o usuário disse explicitamente que quer revisar o texto depois,
que hoje usa 4 "frentes" diferentes de abordagem).

Placeholders disponíveis no assunto/corpo: {razao_social}, {cnpj} e
{link_cta} (o link vira automaticamente um link rastreável — não precisa
mexer na URL na hora de editar o texto, só onde ele aparece na frase).
`link_cta` de cada template é editável separadamente (é a URL de destino
real por trás do link rastreado).
"""

from __future__ import annotations

from src.campaigns.models import TIPO_INICIAL, TIPOS_FOLLOWUP

_LINK_CTA_PADRAO = "https://leactis.com.br"

DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    TIPO_INICIAL: {
        "assunto": "[RASCUNHO] {razao_social} — pendência com a PGFN",
        "corpo": (
            "Olá,\n\n"
            "Identificamos que {razao_social} (CNPJ {cnpj}) consta na Lista de "
            "Devedores da PGFN. Podemos ajudar a regularizar essa situação.\n\n"
            "[AJUSTAR: texto de abordagem inicial — este é só um rascunho.]\n\n"
            "Saiba mais: {link_cta}\n\n"
            "Atenciosamente,\nLeactis"
        ),
        "link_cta": _LINK_CTA_PADRAO,
    },
    TIPOS_FOLLOWUP[0]: {
        "assunto": "[RASCUNHO] Re: {razao_social} — pendência com a PGFN",
        "corpo": (
            "Olá novamente,\n\n"
            "Reforçando o contato anterior sobre a pendência de {razao_social} "
            "(CNPJ {cnpj}) na PGFN.\n\n"
            "[AJUSTAR: texto do 1º follow-up.]\n\n"
            "Saiba mais: {link_cta}\n\n"
            "Atenciosamente,\nLeactis"
        ),
        "link_cta": _LINK_CTA_PADRAO,
    },
    TIPOS_FOLLOWUP[1]: {
        "assunto": "[RASCUNHO] {razao_social} — ainda podemos ajudar",
        "corpo": (
            "Olá,\n\n"
            "[AJUSTAR: texto do 2º follow-up.]\n\n"
            "Saiba mais: {link_cta}\n\n"
            "Atenciosamente,\nLeactis"
        ),
        "link_cta": _LINK_CTA_PADRAO,
    },
    TIPOS_FOLLOWUP[2]: {
        "assunto": "[RASCUNHO] {razao_social} — última tentativa de contato",
        "corpo": (
            "Olá,\n\n"
            "[AJUSTAR: texto do 3º e último follow-up.]\n\n"
            "Saiba mais: {link_cta}\n\n"
            "Atenciosamente,\nLeactis"
        ),
        "link_cta": _LINK_CTA_PADRAO,
    },
}
