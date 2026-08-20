# Capta • ó de clientes

Automação de prospecção e vendas para freelancers/devs solo, inspirado no
posicionamento do produto "Capta".

## Módulo atual: Prospecção (achar leads sem site)

Busca empresas locais por categoria via Google Places API e filtra as que
**não têm site cadastrado** — o público mais fácil de converter em cliente
de um freelancer que vende sites/sistemas.

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env  # e preencha GOOGLE_PLACES_API_KEY
```

Você precisa de uma chave de API do Google com a **Places API (legacy)**
habilitada. Veja https://developers.google.com/maps/documentation/places/web-service/get-api-key.
Atenção: essa API é paga acima da cota gratuita mensal do Google Cloud.

### Uso

```bash
python -m src.prospecting.cli --query "dentista" --location "São Paulo, SP" --output leads.csv
```

Gera um CSV com nome, telefone, endereço, avaliação e link do Google Maps
de cada estabelecimento encontrado sem website.

Opções:

- `--max-results`: máximo de resultados a escanear (até 60, limite da Text Search).
- `--api-key`: sobrescreve `GOOGLE_PLACES_API_KEY` do `.env`.

### Testes

```bash
python -m pytest -q
```

## Roadmap (por viabilidade)

| Módulo | Viabilidade | Status |
| --- | --- | --- |
| Prospecção (achar sem site) | Fácil | ✅ MVP implementado |
| Proposta/contrato em PDF | Fácil | Planejado |
| Análise de call | Médio | Planejado |
| Inbox + sugestão de resposta | Médio | Planejado |
| Disparo automático WhatsApp | Arriscado (API não-oficial = risco de ban) | Não priorizado |
