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

## Módulo: Proposta/contrato em PDF

A partir do briefing de um cliente (texto livre), gera automaticamente uma
**proposta comercial** e um **contrato de prestação de serviço**, ambos em
PDF pronto para enviar — sem precisar de Canva. A geração de conteúdo usa a
API da Claude (Anthropic); a diagramação em PDF é feita localmente com
`reportlab`.

### Setup adicional

Além do setup acima, você precisa de uma chave da API da Anthropic — defina
`ANTHROPIC_API_KEY` no seu `.env` (veja `.env.example`).

Copie o perfil de exemplo e edite com seus dados (nome, serviços, tom de voz,
precificação, condições de pagamento, cláusulas padrão):

```bash
cp profiles/freelancer_profile.example.yaml profiles/freelancer_profile.yaml
```

### Uso

```bash
python -m src.proposals.cli --briefing examples/briefing_exemplo.txt
```

Gera `output/proposta.pdf` e `output/contrato.pdf`. Use `--profile` para
apontar para outro arquivo de perfil, e `--output-dir` para mudar o destino.

### Testes

```bash
python -m pytest -q
```

## Módulo: Análise pós-call

Revisa a transcrição de uma call de vendas como um "code review, mas pra
conversa": dá uma nota, lista os pontos fortes, aponta o **único bug mais
grave** que provavelmente custou o fechamento, sugere como corrigi-lo, e
destaca os momentos-chave da conversa. Gera um relatório em PDF.

### Setup adicional

Usa a mesma `ANTHROPIC_API_KEY` do módulo de propostas. Se você já tem a
transcrição em texto, não precisa de mais nada. Para transcrever áudio
localmente com Whisper (não envia o áudio para nenhuma API):

```bash
pip install -r requirements-whisper.txt  # também requer o binário `ffmpeg`
```

### Uso

```bash
# a partir de uma transcrição já pronta
python -m src.call_analysis.cli --transcript examples/transcript_exemplo.txt

# a partir de um áudio (transcreve localmente com Whisper primeiro)
python -m src.call_analysis.cli --audio call.mp3 --whisper-model base
```

Gera `output/analise_call.pdf` e imprime a nota e o "bug" principal no
terminal. Use `--context` para passar um `.txt` com informações adicionais
(o que estava sendo vendido, preço, etc.) que ajudem a análise.

### Testes

```bash
python -m pytest -q
```

## Módulo: Inbox + sugestão de resposta

Recebe uma mensagem de um lead/cliente (email, WhatsApp, formulário — o canal
não importa, você só passa o texto) e sugere uma resposta pronta no seu tom,
já classificando categoria (dúvida, objeção de preço, orçamento, fechamento,
reclamação...) e prioridade. Funciona tanto por linha de comando (teste
local) quanto como um webhook HTTP simples para plugar em qualquer
integração (Zapier, n8n, um bot de WhatsApp, etc.).

### Setup adicional

Usa a mesma `ANTHROPIC_API_KEY` e o mesmo `profiles/freelancer_profile.yaml`
dos módulos anteriores.

### Uso

```bash
# teste local, uma mensagem por vez
python -m src.inbox.cli --message-text "Oi, quanto custa um site?"

# com histórico da conversa, para respostas com mais contexto
python -m src.inbox.cli --message mensagem.txt --thread-history historico.txt

# webhook: POST {"message": "...", "thread_history": "..."} em /webhook
python -m src.inbox.cli --serve --port 8000
```

O modo `--serve` sobe um servidor local (Flask) com `GET /health` e
`POST /webhook`, que responde com JSON (`category`, `priority`,
`suggested_reply`, `reasoning`) — pronto para conectar a qualquer fonte de
mensagens que consiga fazer uma chamada HTTP.

### Testes

```bash
python -m pytest -q
```

## Roadmap (por viabilidade)

| Módulo | Viabilidade | Status |
| --- | --- | --- |
| Prospecção (achar sem site) | Fácil | ✅ MVP implementado |
| Proposta/contrato em PDF | Fácil | ✅ MVP implementado |
| Análise de call | Médio | ✅ MVP implementado |
| Inbox + sugestão de resposta | Médio | ✅ MVP implementado |
| Disparo automático WhatsApp | Arriscado (API não-oficial = risco de ban) | Não priorizado |
