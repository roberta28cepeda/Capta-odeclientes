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

A lista da PGFN **não inclui e-mail nem telefone**. Use `--enrich-contato`
pra buscar o telefone público de cada CNPJ (o mesmo cadastrado na Receita
Federal, via BrasilAPI — a mesma consulta usada na Pré-Análise Fiscal do
módulo `fiscal_monitor`):

```bash
python -m src.prospecting.pgfn_cli --csv devedores.csv --enrich-contato
```

Isso não é um enriquecimento comercial completo (não traz e-mail, não é
opt-in de marketing) — é só o telefone público, melhor que sair sem
contato nenhum. Um CNPJ não encontrado ou fora do ar fica sem telefone,
sem travar o resto da lista.

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

## Módulo: Monitoramento Fiscal (estilo Veri)

Produto de carteira: um escritório contábil (tenant) cadastra os CNPJs
dos seus clientes — com o **regime tributário** de cada um (MEI, Simples,
Presumido, Real) — e importa achados fiscais: pendências, multas,
notificações (Federal/Estadual/Municipal), guias **DAS**, **CNDs**
(certidões negativas, com data de validade), **parcelamentos** (parcelas
de acordos fiscais) e mensagens de **caixa postal do e-CAC**. O sistema
compara cada importação com a anterior, classifica cada achado como
**nova** / **recorrente** / **resolvida**, prioriza o que merece alerta
(achado novo, ou DAS/CND/parcelamento perto do vencimento), monitora o
**sublimite/teto do Simples Nacional** por faturamento acumulado de 12
meses, e disponibiliza tudo num dashboard web com histórico por CNPJ —
inspirado nas funcionalidades da [Veri](https://veri.com.br/), mas pensado
desde já como produto multi-tenant pra vender a outros escritórios, não só
uso interno.

### Pré-análise fiscal pública (sem procuração, sem e-CAC)

Resolve a dor de abordar um cliente que ainda não quer dar procuração ou
acesso ao e-CAC: com **só o CNPJ**, consulta dados que já são públicos —
situação cadastral, natureza jurídica, porte, e se a empresa é optante
pelo **Simples Nacional** ou **MEI** — via [BrasilAPI](https://brasilapi.com.br/),
um espelho gratuito e sem autenticação dos dados que a Receita Federal já
publica. Gera um PDF pronto pra levar na reunião, **antes** de pedir
qualquer acesso. Ao contrário do resto do módulo, isso funciona **hoje**,
sem depender de certificado digital nem de contrato com ninguém.

```bash
python -m src.fiscal_monitor.cli --pre-analise --cnpj 11.222.333/0001-44 \
    --escritorio-nome "Seu Escritório" --logo caminho/da/sua/logo.png
```

Gera `output/pre_analise_<cnpj>.pdf`. `--logo` é opcional.

**Também dá pra gerar direto pelo navegador**, sem terminal — útil pra usar
na hora, numa reunião: suba o dashboard (`--serve`) e acesse
`/pre-analise`. É um formulário (CNPJ, nome do escritório opcional, logo
opcional) que baixa o PDF na hora, com validação de dígito verificador do
CNPJ antes de consultar.

**O que isso não traz:** pendências, multas e dívidas fiscais são dado
privado — exigem procuração eletrônica e acesso ao e-CAC (a parte do
módulo que só funciona hoje via CSV importado manualmente, ou no futuro
via Serpro Integra Contador, ver abaixo). A pré-análise é só a porta de
entrada da conversa, não substitui a checagem completa.

### O que este MVP não faz (ainda)

A Veri e concorrentes puxam dado ao vivo do e-CAC via **Serpro Integra
Contador** — o canal oficial homologado pela Receita Federal (não é
scraping). Pra ativar essa integração de verdade falta:

1. Contrato de consumo com o Serpro (pago por chamada de API).
2. Procuração eletrônica assinada por cada cliente contábil, autorizando o
   escritório a consultar os dados fiscais dele via essa API.
3. Certificado digital (e-CNPJ) do escritório, pra autenticar as chamadas.

Sem essas três coisas em mãos não dá pra implementar de forma testável —
o terreno já está preparado (`src/fiscal_monitor/providers.py`, classe
`SerproIntegraContadorProvider`, que implementa a interface
`FiscalDataProvider` mas levanta `NotImplementedError` documentando
exatamente isso), mas a chamada real fica para quando o contrato/certificado
existirem.

Por enquanto os achados fiscais e o faturamento entram via **CSV**
(`--import-snapshot` / `--import-faturamento`) — de um export manual do
e-CAC feito pelo próprio escritório, ou de qualquer scraper que ele já
use. O sistema cuida do diff, priorização, alerta e dashboard.

### Setup adicional

Usa `WHATSAPP_ACCESS_TOKEN`/`WHATSAPP_PHONE_NUMBER_ID` do módulo de
WhatsApp (opcional, só pra `--enviar-whatsapp`) e, opcionalmente,
`SMTP_HOST`/`SMTP_PORT`/`SMTP_USERNAME`/`SMTP_PASSWORD`/`SMTP_FROM` pra
alerta por e-mail (`--enviar-email`) — o escritório pode receber alerta
por WhatsApp, e-mail, ou os dois, dependendo do que cadastrar no contato.
Não precisa de mais nada além do `requirements.txt` já instalado — a
persistência é SQLite puro (stdlib) local, ou Postgres em produção (ver
"Deploy no Vercel" abaixo).

### Uso

```bash
# cadastra um escritório (tenant) e sua carteira de CNPJs (com regime tributário)
python -m src.fiscal_monitor.cli --import-tenant --nome "Escritório X" --whatsapp 5511999999999 --email contato@escritorio.com.br
python -m src.fiscal_monitor.cli --import-portfolio --tenant-id 1 --csv carteira.csv

# importa achados fiscais (cnpj,esfera,tipo,descricao,valor,vencimento,pago)
# tipos aceitos: pendencia, multa, notificacao, das, cnd, parcelamento, caixa_postal
python -m src.fiscal_monitor.cli --import-snapshot --tenant-id 1 --csv snapshot_ecac.csv

# importa faturamento mensal (cnpj,competencia,valor) — usado no sublimite do Simples
python -m src.fiscal_monitor.cli --import-faturamento --tenant-id 1 --csv faturamento.csv

# roda o motor de alertas (achados + sublimite do Simples), opcionalmente gerando PDF e enviando por WhatsApp/e-mail
python -m src.fiscal_monitor.cli --check --tenant-id 1 --dias-alerta 5 --referencia 2026-09
python -m src.fiscal_monitor.cli --check --tenant-id 1 --pdf --enviar-whatsapp --enviar-email

# dashboard web (tenants, carteira com regime, sublimite, achados em aberto e histórico por CNPJ)
python -m src.fiscal_monitor.cli --serve --port 8090
```

Veja `examples/fiscal_monitor_carteira_exemplo.csv`,
`examples/fiscal_monitor_snapshot_exemplo.csv` e
`examples/fiscal_monitor_faturamento_exemplo.csv` para o formato esperado.

**Cadastro de escritório também dá pra fazer pelo navegador**, sem
terminal: com login de admin (`ADMIN_USERNAME`/`ADMIN_PASSWORD`), acesse
`/admin/tenants/novo` no dashboard — formulário com nome, WhatsApp,
e-mail, plano e upload direto da carteira em CSV.

### Testes

```bash
python -m pytest -q
```

### Deploy no Vercel (dashboard acessível pela internet)

Por padrão o módulo usa SQLite local (arquivo em `output/`) — funciona
bem local/CLI, mas **não serve pra hospedar**: funções serverless (como
as do Vercel) não têm disco persistente entre execuções. Por isso, em
produção o módulo troca automaticamente pra **Postgres** assim que uma
destas variáveis de ambiente existir: `DATABASE_URL`, `POSTGRES_URL` ou
`POSTGRES_URL_NON_POOLING` (é o que a integração de banco do Vercel
injeta sozinha ao conectar um Postgres ao projeto). O schema é criado
automaticamente na primeira conexão — não precisa rodar migration à parte.

Passos:

1. No projeto Vercel, aba **Storage** → **Create Database** → Postgres —
   isso já injeta a variável de conexão certa no projeto.
2. Configure as outras variáveis que os módulos usam (`ANTHROPIC_API_KEY`,
   `WHATSAPP_ACCESS_TOKEN`, etc., conforme o que for usar) em
   **Settings → Environment Variables**.
3. Deploy — o Vercel usa `api/index.py` (expõe o dashboard Flask de
   `src/fiscal_monitor/server.py`) e `vercel.json` já prontos no repo.

O `/pre-analise` funciona igual, servindo o PDF direto do navegador. Os
outros módulos (`prospecting`, `proposals`, `whatsapp`, etc.) continuam
sendo CLI local — só o `fiscal_monitor` tem essa camada web pensada pra
hospedagem.

## Roadmap (por viabilidade)

| Módulo | Viabilidade | Status |
| --- | --- | --- |
| Prospecção (achar sem site) | Fácil | ✅ MVP implementado |
| Prospecção via Lista de Devedores PGFN | Fácil | ✅ MVP implementado |
| Proposta/contrato em PDF | Fácil | ✅ MVP implementado |
| Análise de call | Médio | ✅ MVP implementado |
| Inbox + sugestão de resposta | Médio | ✅ MVP implementado |
| WhatsApp via Cloud API oficial | Antes "arriscado" (API não-oficial); via Meta é burocrático mas seguro | ✅ MVP implementado |
| Monitoramento Fiscal — pré-análise pública (só CNPJ, sem procuração) | Fácil | ✅ MVP implementado |
| Monitoramento Fiscal (estilo Veri) — via CSV, com CND/parcelamento/sublimite Simples | Médio | ✅ MVP implementado |
| Monitoramento Fiscal — integração real via Serpro Integra Contador (canal oficial Receita Federal) | Difícil (contrato Serpro + certificado digital) | ⏳ Terreno preparado (`SerproIntegraContadorProvider`), não ativado — ver seção acima |
