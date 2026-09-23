"""Entrypoint que o Vercel executa: expõe o dashboard do monitoramento
fiscal (`src/fiscal_monitor/server.py`) como função serverless.

`create_app()` sem argumento usa Postgres automaticamente quando
DATABASE_URL/POSTGRES_URL está definida no ambiente do Vercel (ver
`src/fiscal_monitor/storage.py`) — sem isso, cairia no SQLite local, que
não persiste entre invocações serverless.
"""

from src.fiscal_monitor.server import create_app

app = create_app()
