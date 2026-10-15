"""Autenticação/autorização de admin compartilhada entre os módulos com
dashboard web (`fiscal_monitor`, `campaigns`) — HTTP Basic Auth, com duas
camadas:

1. Usuário/senha "mestre" via `ADMIN_USERNAME`/`ADMIN_PASSWORD` (env var) —
   acesso de emergência/bootstrap, sempre disponível mesmo se o banco cair.
   É sempre o teto de permissão (papel "mestre"), nunca gravado em linha
   nenhuma do banco.
2. Contas individuais por pessoa da equipe, guardadas em `admin_users`
   (tabela do `fiscal_monitor.storage`), cada uma com um `papel` gravado
   (`leitor` < `operador` < `gestor`) — permite saber quem acessou o quê,
   revogar o acesso de uma pessoa sem trocar a senha de todo mundo, e
   restringir o que cada papel pode fazer (gerenciadas em `/admin/usuarios`).
"""

from __future__ import annotations

import os
import secrets

from flask import Response, current_app, request
from werkzeug.security import check_password_hash

PAPEL_MESTRE = "mestre"
_PAPEL_ORDEM = {"leitor": 1, "operador": 2, "gestor": 3}


def current_papel() -> str | None:
    """Papel da credencial autenticada na requisição atual, ou None se não
    autenticada. "mestre" é devolvido pro login via env var (sempre o teto,
    nunca checado contra `_PAPEL_ORDEM`); senão é o `AdminUser.papel`."""
    auth = request.authorization
    if not auth:
        return None

    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if (
        admin_password
        and secrets.compare_digest((auth.username or "").encode("utf-8"), admin_username.encode("utf-8"))
        and secrets.compare_digest((auth.password or "").encode("utf-8"), admin_password.encode("utf-8"))
    ):
        return PAPEL_MESTRE

    return _papel_via_admin_user(auth.username or "", auth.password or "")


def _papel_via_admin_user(username: str, password: str) -> str | None:
    if not username or not password:
        return None
    from src.fiscal_monitor import storage

    db_path = current_app.config.get("DB_PATH", storage.DEFAULT_DB_PATH)
    conn = storage.connect(db_path)
    try:
        user = storage.get_admin_user_by_username(conn, username)
    finally:
        conn.close()
    if user is None or not user.ativo or not check_password_hash(user.password_hash, password):
        return None
    return user.papel


def admin_authenticated() -> bool:
    return current_papel() is not None


def require_admin() -> Response | None:
    if admin_authenticated():
        return None
    return Response(
        "Autenticação necessária.", 401, {"WWW-Authenticate": 'Basic realm="Capta"'}
    )


def require_papel(papel_minimo: str) -> Response | None:
    """Gate de autorização por papel — 401 (com `WWW-Authenticate`, reabre
    o prompt Basic Auth do navegador) se não autenticado; 403 (sem esse
    header — a senha já está certa, só falta permissão) se autenticado mas
    com papel insuficiente; None se autorizado (inclui sempre o mestre)."""
    papel = current_papel()
    if papel is None:
        return Response(
            "Autenticação necessária.", 401, {"WWW-Authenticate": 'Basic realm="Capta"'}
        )
    if papel == PAPEL_MESTRE or _PAPEL_ORDEM.get(papel, 0) >= _PAPEL_ORDEM[papel_minimo]:
        return None
    return Response("Acesso não autorizado para este papel.", 403)


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
