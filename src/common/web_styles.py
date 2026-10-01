"""CSS compartilhado pelas páginas HTML server-side do dashboard
(`fiscal_monitor/server.py`, `campaigns/routes.py`) — sem framework JS nem
build step, consistente com o resto do repo. Uma folha de estilo só, puro
CSS, injetada via `page()` em cada template.
"""

from __future__ import annotations

BASE_STYLE = """
<style>
  :root {
    --accent: #0f766e;
    --accent-dark: #0b5c56;
    --bg: #f5f6f8;
    --card-bg: #ffffff;
    --border: #e3e5e9;
    --text: #1f2430;
    --text-muted: #6b7280;
    --danger: #b23a48;
    --success: #1a7a3c;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
  }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }
  h1 { font-size: 1.6rem; margin: 0 0 .25rem; }
  h2 { font-size: 1.1rem; margin: 2rem 0 .75rem; color: var(--accent-dark); }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  p { margin: .5rem 0; }
  .nav { display: flex; flex-wrap: wrap; gap: .5rem; margin: 1rem 0 1.5rem; padding: 0; list-style: none; }
  .nav a {
    background: var(--card-bg); border: 1px solid var(--border);
    padding: .4rem .9rem; border-radius: 999px; font-size: .88rem; color: var(--text);
  }
  .nav a:hover { border-color: var(--accent); color: var(--accent); text-decoration: none; }
  .tabs { margin: .5rem 0 1.5rem; }
  .tabs a { margin-right: .75rem; font-size: .92rem; }
  .tabs a.ativa { font-weight: 700; color: var(--accent-dark); }
  .card {
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 10px; padding: 1.25rem 1.5rem; margin-bottom: 1.5rem;
  }
  table { width: 100%; border-collapse: collapse; background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; }
  th, td { text-align: left; padding: .6rem .9rem; border-bottom: 1px solid var(--border); font-size: .92rem; }
  th { background: #fafbfc; color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: .72rem; letter-spacing: .03em; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #fafbfc; }
  label { display: block; margin-bottom: 1rem; font-size: .9rem; }
  input[type=text], input[type=password], input[type=email], input[type=number],
  input[type=date], input[type=file], select, textarea {
    display: block; width: 100%; max-width: 420px; padding: .5rem .65rem; margin-top: .35rem;
    border: 1px solid var(--border); border-radius: 6px; font-size: .92rem; font-family: inherit;
    background: #fff; color: var(--text);
  }
  textarea { max-width: 100%; }
  input:focus, select:focus, textarea:focus {
    outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(15,118,110,.12);
  }
  button {
    background: var(--accent); color: #fff; border: none; padding: .55rem 1.2rem;
    border-radius: 6px; font-size: .9rem; font-weight: 600; cursor: pointer;
  }
  button:hover { background: var(--accent-dark); }
  .inline { display: inline; }
  .alert, .success {
    padding: .7rem 1rem; border-radius: 6px; margin-bottom: 1rem; font-size: .9rem; border-left: 4px solid;
  }
  .alert { background: #fdf0f1; border-color: var(--danger); color: var(--danger); }
  .success { background: #edf9f0; border-color: var(--success); color: var(--success); }
  code { background: #f1f2f4; padding: .1rem .4rem; border-radius: 4px; font-size: .85em; }
  hr { border: none; border-top: 1px solid var(--border); margin: 2rem 0; }
  small { color: var(--text-muted); }
</style>
"""


def page(title: str, body: str) -> str:
    """Envelope HTML comum (doctype/head/estilo/wrap) pra um corpo de
    template Jinja já pronto. `title` pode conter sintaxe Jinja (ex:
    `"{{ tenant.nome }}"`) — o resultado inteiro ainda passa por
    `render_template_string` depois.
    """
    return f"""<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{BASE_STYLE}
</head>
<body>
<div class="wrap">
{body}
</div>
</body>
</html>"""
