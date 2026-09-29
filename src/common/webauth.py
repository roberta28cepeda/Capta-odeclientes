"""Autenticação de admin compartilhada entre os módulos com dashboard web
(`fiscal_monitor`, `campaigns`) — mesma senha (`ADMIN_USERNAME`/
`ADMIN_PASSWORD`) pra todo o sistema, HTTP Basic Auth.
"""

from __future__ import annotations

import os
import secrets

from flask import Response, request


def admin_authenticated() -> bool:
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_password:
        return False
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    auth = request.authorization
    if not auth:
        return False
    return secrets.compare_digest(auth.username or "", admin_username) and secrets.compare_digest(
        auth.password or "", admin_password
    )


def require_admin() -> Response | None:
    if admin_authenticated():
        return None
    return Response(
        "Autenticação necessária.", 401, {"WWW-Authenticate": 'Basic realm="Capta"'}
    )


def cron_authorized() -> bool:
    """Protege endpoints de cron: aceita CRON_SECRET no header Authorization
    (formato que o Vercel Cron manda sozinho) ou em ?secret=... (schedulers
    externos). Sem CRON_SECRET configurado, o acesso é sempre negado.
    """
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        return False
    auth_header = request.headers.get("Authorization", "")
    if secrets.compare_digest(auth_header, f"Bearer {secret}"):
        return True
    return secrets.compare_digest(request.args.get("secret", ""), secret)
