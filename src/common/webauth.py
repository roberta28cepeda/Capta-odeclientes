"""Autenticação de admin compartilhada entre os módulos com dashboard web
(`fiscal_monitor`, `campaigns`) — HTTP Basic Auth, com duas camadas:

1. Usuário/senha "mestre" via `ADMIN_USERNAME`/`ADMIN_PASSWORD` (env var) —
   acesso de emergência/bootstrap, sempre disponível mesmo se o banco cair.
2. Contas individuais por pessoa da equipe, guardadas em `admin_users`
   (tabela do `fiscal_monitor.storage`) — permite saber quem acessou o quê
   e revogar o acesso de uma pessoa sem trocar a senha de todo mundo
   (gerenciadas em `/admin/usuarios`).
"""

from __future__ import annotations

import os
import secrets

from flask import Response, current_app, request
from werkzeug.security import check_password_hash


def admin_authenticated() -> bool:
    auth = request.authorization
    if not auth:
        return False

    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if (
        admin_password
        and secrets.compare_digest(auth.username or "", admin_username)
        and secrets.compare_digest(auth.password or "", admin_password)
    ):
        return True

    return _authenticated_via_admin_user(auth.username or "", auth.password or "")


def _authenticated_via_admin_user(username: str, password: str) -> bool:
    if not username or not password:
        return False
    from src.fiscal_monitor import storage

    db_path = current_app.config.get("DB_PATH", storage.DEFAULT_DB_PATH)
    conn = storage.connect(db_path)
    try:
        user = storage.get_admin_user_by_username(conn, username)
    finally:
        conn.close()
    if user is None or not user.ativo:
        return False
    return check_password_hash(user.password_hash, password)


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
