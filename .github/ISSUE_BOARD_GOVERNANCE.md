# Governança de Issues — Cypher65 War Room

Última atualização: **2026-09-29**.

Este arquivo serve de verdade para evitar duas armadilhas comuns:
- achar que um issue está “feito” só porque há um PR; e
- fingir que um issue está “pronto para PR” quando depende de decisão, recurso externo ou hardware.

Ele é atualizado à medida que algo muda de porta.

## Portas de fechamento

1. **PR no repo (quando possível)**  
   Um branch com uma só regra: um issue por PR, `Closes #NNN`, CI verde antes de considerar aberto, sem push direto para `master`, sem merge por aqui. Só entra nessa porta o que tem implementação/testes/config reais dentro do repo.

2. **Bloqueio externo ou decisão pendente**  
   Issue não é “PR-ável” agora. Exemplos comuns aqui:  
   - depende de credencial/env/produção configurada fora do repo;  
   - depende de hardware/dispositivo físico disponível;  
   - depende de fonte externa real de dados que não temos;  
   - depende de decisão de produto/SLO/config de deploy.  

   Nesses casos, o rastreio fica explícito e o item não recebe PR “para fechar por conta”.

3. **Governança manual em separado**  
   Usado quando já existe PR na GitHub, mas o estado do issue não é só “mesmo autor abriu + fechou”. Exemplo atual: #622, que já teve PR mergeado externamente e depois reaberto com observação sobre o merge, com PR complementar #674 aberto. A decisão de fechar ou não é política/review/external-merge, não mudança de código local.

## Status atual (2026-09-29)

### Abrir PRs agora (dentro do repo)

- **#609** — branch `test/609-telemetry-validation` com alterações locais; fazer commit + PR com `Closes #609` somente quando necessário, sem merge.

### Bloqueio externo / não-PR-ável agora

- **#22** — Postgres gated por tração e decisão operacional; não é PR de código agora.
- **#330** — ativar canal BTC em produção com env vars/render/docs; depende de decisão/produção, não de um PR de lógica apenas.
- **#386** — matriz física com hardware/dispositivos; evidência física bloqueada externamente.
- **#399** — épico iOS + Universal SHA-256 Pool Intelligence; escopo amplo e bloqueios externos (hardware/signing/credenciais/etc.).
- **#600** — faixa floor/ceiling em custo/energia; está blocked-external até fonte consumível de floor/ceiling (Issue já declarou esse bloqueio).
- **#659** — reconhecimento do BTC PoW Lab; é proposta de integração/provedor real; avaliar se cabe como PR ou como item de follow-up externo antes de abrir branch.

### Issue de teste/cobertura (muitos P2/P3, muitos com arquivos sugeridos que não existem)

Ainda precisa de decisão de se criar arquivo novo ou reforçar cobertura existente. Exemplos:
- **#598, #599** — features de payout/rentals com frontend + backend; podem virar PR, mas exigem escopo de mudança real, não só arquivo de teste.
- **#606, #607** — performance com SLO bloqueado; #606 explicitamente bloqueado até SLO acordado.
- **#608, #610, #611, #612, #614, #629** — lacunas de cobertura/eventos; possível PR de teste/observabilidade, mas muitos deles pedem novo arquivo/spec e alguns dependem de outro item antes.
- **#668, #669, #670** — scanner/agent/sim; alguns são PR-áveis, alguns têm parte doc/teste e podem precisar de mais scoping.

### Ja em governança externa/separada

- **#622** — em estado aberto com rastreio de merge externo do #673 e PR complementar #674; decisão de fechamento é externa/governança, não mudança de código local.
- **#673** — merged externamente (PR #673), fora do controle local de merge.
- **#674** — PR aberto propondo formatação complementar para #622; sem merge.

## Regra prática

- Seçõ escrita como “PR agora”, mas não há código/testes/repo-reais suficientes, o issue vai para “não-PR-ável agora” com motivo.
- Seçõ puder ser PR, mas depender de outro issue/env/fontes/hardware, vai para bloqueio.
- Nada aqui inventa credencial, dispositivo, fonte externa ou decisão de produto.

> **Nota:** eu não faço merge e não posso assumir que o CI ou review externo aprovaram algo. Prescrever merge/production é fora dos meus controles; o que eu faço é entregar o PR/PR-possível + registrar o que não é.
