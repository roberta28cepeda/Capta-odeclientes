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

## Módulo: Prospecção via Lista de Devedores da PGFN

Fonte de lead alternativa, sem depender de API paga: parseia o export CSV
da **Lista de Devedores da PGFN** (dívida ativa da União) e segmenta as
empresas por **tier de valor da dívida** — um sinal de dor bem mais forte
que "não tem site", especialmente pra contadores (regularização fiscal) e
transportadoras (dívida trava financiamento de frota e licitação).

O export da PGFN não é um CSV limpo: tem um preâmbulo de metadados antes do
cabeçalho real e vem em ISO-8859-1 (latin-1) — o parser já trata isso.

### Uso

```bash
python -m src.prospecting.pgfn_cli --csv devedores.csv --output leads_pgfn.csv
```

Gera um CSV com CNPJ, razão social, nome fantasia, valor da dívida
selecionada, valor total, tipo de registro (pessoa física/EI vs empresa
constituída) e **tier** (A ≥R$500 mil, B R$100-500 mil, C R$20-100 mil, D
<R$20 mil). Imprime também a concentração de Pareto — tipicamente uma
fração pequena das empresas concentra a maior parte da dívida, priorize
por aí.

A lista da PGFN **não inclui e-mail nem telefone** — falta enriquecer
contato antes de abordar (não implementado aqui ainda).

### Testes

```bash
python -m pytest -q
```

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

## Módulo: WhatsApp via Cloud API oficial (Meta)

Envia e recebe mensagens de WhatsApp usando a **WhatsApp Cloud API oficial**
da Meta — não a API não-oficial (que arrisca banir o número do cliente).
Dá pra: mandar um texto, mandar a proposta/contrato em PDF já gerados pelo
módulo de propostas, e receber mensagens por webhook, reaproveitando o
mesmo gerador de resposta sugerida do módulo de inbox.

### Como funciona (e as pegadinhas da API oficial)

- **Enviar mensagem de texto livre** só funciona dentro da janela de 24h
  depois do cliente escrever para você primeiro. Fora dessa janela, a Meta
  exige um **template de mensagem pré-aprovado** (não implementado aqui —
  é configurado no painel do WhatsApp Manager e leva alguns dias para
  aprovação).
- **Enviar documento (PDF)** segue a mesma regra da janela de 24h.
- **Receber mensagens** chega por webhook, sem restrição de janela.
- Por padrão, `--serve` só **sugere** a resposta e imprime no terminal —
  não envia nada sozinho. Envio automático é opt-in via `--auto-reply` e
  deve ser usado com cautela (resposta gerada por LLM, sem revisão humana,
  saindo em nome do freelancer).

### Setup

1. Crie um app no [Meta for Developers](https://developers.facebook.com/apps/)
   com o produto **WhatsApp** e siga a verificação de negócio.
2. No painel do app, pegue o `access_token` (temporário para testes,
   permanente para produção) e o `phone_number_id` do número de teste ou do
   seu número verificado.
3. Preencha no `.env`: `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` e
   `WHATSAPP_VERIFY_TOKEN` (você escolhe esse valor e configura o mesmo no
   painel de configuração do webhook).
4. Para receber mensagens, o webhook precisa de uma URL pública (ex.: um
   túnel `ngrok` apontando para `--serve` durante o desenvolvimento).

### Uso

```bash
# enviar texto (só dentro da janela de 24h após o cliente escrever)
python -m src.whatsapp.cli --to 5511999999999 --send-text "Oi! Tudo bem?"

# enviar a proposta em PDF já gerada
python -m src.whatsapp.cli --to 5511999999999 --send-pdf output/proposta.pdf --caption "Segue a proposta!"

# subir o webhook que recebe mensagens e sugere resposta (sem enviar sozinho)
python -m src.whatsapp.cli --serve --port 8080

# mesmo webhook, mas enviando a resposta sugerida automaticamente (cuidado)
python -m src.whatsapp.cli --serve --auto-reply
```

### Testes

```bash
python -m pytest -q
```

## Roadmap (por viabilidade)

| Módulo | Viabilidade | Status |
| --- | --- | --- |
| Prospecção (achar sem site) | Fácil | ✅ MVP implementado |
| Prospecção via Lista de Devedores PGFN | Fácil | ✅ MVP implementado |
| Proposta/contrato em PDF | Fácil | ✅ MVP implementado |
| Análise de call | Médio | ✅ MVP implementado |
| Inbox + sugestão de resposta | Médio | ✅ MVP implementado |
| WhatsApp via Cloud API oficial | Antes "arriscado" (API não-oficial); via Meta é burocrático mas seguro | ✅ MVP implementado |
