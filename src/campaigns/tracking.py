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


def pixel_img_tag(base_url: str, tracking_token: str) -> str:
    return f'<img src="{pixel_url(base_url, tracking_token)}" width="1" height="1" alt="" style="display:none">'
