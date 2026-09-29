"""Pixel de abertura + link de clique rastreável, pros e-mails da campanha.

O rastreio real de abertura só funciona em cliente de e-mail que carrega
imagem remota (a maioria dos webmails; alguns como o Apple Mail pré-
carregam sempre, o que infla a taxa de abertura — limitação conhecida
desse tipo de rastreio, não só nossa).
"""

from __future__ import annotations

from urllib.parse import urlencode

# GIF transparente 1x1 — corpo mínimo válido de imagem, usado só pra
# registrar a requisição (o pixel em si nunca é exibido).
PIXEL_GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f9040100000000002c00000000010001000002024401003b"
)


def pixel_url(base_url: str, tracking_token: str) -> str:
    return f"{base_url.rstrip('/')}/track/open/{tracking_token}.gif"


def click_url(base_url: str, tracking_token: str, destino: str) -> str:
    return f"{base_url.rstrip('/')}/track/click/{tracking_token}?{urlencode({'url': destino})}"


def texto_para_html(texto: str) -> str:
    """Escapa e converte quebra de linha simples em <br> — o suficiente pra
    um e-mail de texto corrido, sem precisar de um template HTML completo.
    """
    escapado = (
        texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return escapado.replace("\n", "<br>\n")


def montar_corpo_html(texto_formatado: str, base_url: str, tracking_token: str) -> str:
    corpo_html = texto_para_html(texto_formatado)
    pixel = f'<img src="{pixel_url(base_url, tracking_token)}" width="1" height="1" alt="" style="display:none">'
    return f"<html><body>{corpo_html}{pixel}</body></html>"
