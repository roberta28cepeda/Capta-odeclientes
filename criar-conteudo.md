# /criar-conteudo

Executa o ciclo diário de conteúdo da Leactis (Instagram + LinkedIn), passando pelos papéis definidos em `.claude/agents/`: pesquisador → ganchos → roteirista → designer → gestor → (publicador, só com aprovação).

## Passo a passo

1. Leia `.claude/content-team/briefing.md` para carregar tom, paleta e regras da marca.
2. Leia `.claude/content-team/campanha-ativa.md` e confira se a data de hoje cai dentro do período de alguma campanha listada. Isso muda o comportamento de todos os agentes a seguir (ver seção "Modo campanha" em cada `.claude/agents/*.md`).
3. Confirme que os agentes em `.claude/agents/` existem (pesquisador.md, ganchos.md, roteirista.md, designer.md, gestor.md, publicador.md). Se algum estiver faltando, pare e reporte — não invente o papel do zero.
4. Encarne cada papel na ordem, seguindo exatamente as instruções do arquivo correspondente:
   - **pesquisador** → gera `research.md`
   - **ganchos** → gera `hooks.md`
   - **roteirista** → gera `script.md`
   - **designer** → gera `design-brief.md`
   - **gestor** → gera o resumo final de revisão
5. **PARE antes do publicador.** Nunca publique, agende ou envie nada externamente sem aprovação explícita da Roberta no chat. Regra dura, não sugestão.
6. Salve os 4 arquivos do ciclo do dia (research.md, hooks.md, script.md, design-brief.md) na pasta do ciclo (ex: `/ciclos/AAAA-MM-DD/`).
7. Se estiver rodando em modo assíncrono (sem ninguém observando ao vivo), termine com um resumo claro: tema escolhido e por quê, gancho vencedor e por quê, resumo do roteiro, resumo do conceito visual, e pergunta explícita se aprova seguir ao publicador — deixando claro que a aprovação pode vir a qualquer momento depois.
8. Se faltar uma decisão que só a Roberta pode tomar (oferta nova, dado sem fonte, mudança de posicionamento), sinalize isso claramente no resumo em vez de inventar — mas isso não deve travar o ciclo inteiro; prossiga marcando como "pendente de aprovação".
