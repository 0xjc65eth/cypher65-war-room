# CYPHER65 — RECOVERY REPORT

Data: 2026-10-10, Europe/Brussels. Base GitHub verificada: master `155dcc7a0ce9e725a54e06bba291932a5b8793a4`. Relatório inicial de recuperação; novas unidades #799/#800 terão evidência própria.

## 1. Recovery status

**FATO:** este worktree começou limpo, HEAD destacado em #797. A interrupção recuperada estava no checkout principal `/Users/juliocesar/cypher65-war-room`, branch `fix/798-console-ids-chart-init`, base `ec3bdf6`, um commit atrás da master. Existiam alterações não commitadas em `templates/dashboard.html`, `static/src/39b-dashboard.js`, `static/app.js`, `static/style.css`, `tests/e2e/terminal-console.spec.js` e o mapa `docs/PR1-PR7-SERIES.md` não rastreado.

O diff original foi preservado em `/tmp/c65-original-798.patch` e o mapa em `/tmp/c65-original-series.md`; os arquivos originais e os sete stashes foram mantidos. A recuperação aplica esse diff sobre master no worktree desta conversa, branch `fix/798-frontend-recovery`, e fortalece os pontos encontrados pela revisão. Não houve reset, force-push, merge, deploy ou leitura de secrets.

**Concluído:** identificação do checkpoint, reconstrução PR1–PR7, reparo frontend de #798, testes focados e revisões /devil e /advisor.
**Incompleto:** gates globais quebrados na base e recuperação separada #799/#800. Não presumir que a execução interrompida de check:frontend terminou: esta recuperação reexecutou e observou exit 0.

## 2. GitHub status

A matriz completa está em [PR1–PR7](docs/PR1-PR7-SERIES.md). Os sete ordinais já foram integrados; #793 complementa PR3. Nenhuma implementação duplicada foi aberta. #797 já era MERGED com checks em FAILURE e sem approval no snapshot consultado.

[Issue #798](https://github.com/0xjc65eth/cypher65-war-room/issues/798) já existia, com labels correction, priority: P1, team:frontend e team:qa. Foram abertas [#799](https://github.com/0xjc65eth/cypher65-war-room/issues/799) e [#800](https://github.com/0xjc65eth/cypher65-war-room/issues/800) para bloqueadores independentes antes de editar seus códigos.

As consultas ao GitHub no sandbox falharam; com rede permitida autenticaram e confirmaram a base. Portanto o primeiro aviso de token inválido não foi tratado como credencial realmente inválida.

## 3. Implementation status — #798

| Origem | Falha comprovada | Reparo |
|---|---|---|
| dashboard.html | cinco IDs duplicados e dois scripts app.js + dois stylesheets | IDs de contexto únicos, textContent espelhado, um script e um CSS |
| dashboard.html | abertura inventory duplicada aninhava desk-secondary indevidamente | inventory e secondary voltam a ser irmãos do workspace |
| style.css | bloco :root sem fechamento | restaurado fechamento, regras premium continuam aplicadas |
| 39b-dashboard.js | initCharts recriava dono de canvas; refresh/replacement divergiam | ownership único validado por canvas e Chart.getChart; destroy antes de substituição |
| 39b-dashboard.js | handlers de zoom sobreviviam ao destroy | AbortController liberado em plugin afterDestroy |
| 39b-dashboard.js | respostas fora de ordem/range/JSON/402 atualizavam estado obsoleto | tokens por chart, validação do dono/range e descarte após awaits |
| tests | recuperação removia assertions de firstfold/logout | assertions preservadas; overview agora visible conforme contrato de #797 |

O bundle foi gerado a partir dos 17 fragmentos canônicos; nunca editado manualmente. Chart.js usado pelo template: 4.4.1. Nenhuma dependência de produção adicionada. O carregamento offline sem Chart permanece protegido. Overlays, ranges e mecanismo de licença são preservados.

## 4. CI/CD e validações

| Estado | Comando / ambiente | Resultado observado |
|---|---|---|
| PASS | build_app_js.cjs --check; node --check static/app.js; diff --check | 17 fragmentos sincronizados e sintaxe válida |
| FAIL → PASS | check-dom-regression.cjs --report | reproduziu cinco duplicatas; após reparo, 149 sinks/blocos e IDs únicos |
| PASS | node tests/test_app_js_core.js | 1.694 assertions; 19 novas contra o fragmento real, incluindo async inverso/JSON/402/canvas/cleanup |
| PASS | pytest focado PR1–PR7: hashrate_market, block_probability_lab, session_evidence, economic_scenario_matrix, market_intelligence, rental_performance, command_center, dashboard_routes_migration | 407 passed, 5,04s; sem prova de integração externa |
| PASS | Playwright terminal-console + operational-overview | 46 passed, 1,2min, Chromium e mobile Chromium; firstfold/logout/motion preservados |
| PASS | AUDIT_URL=http://127.0.0.1:8765 npm run check:frontend | pipeline completo: DOM, a11y, tokens, XSS mobile, JS, SW, visual, axe, unidades e mutações |
| FAIL | pytest tests/ -q no sandbox | 191 failed, 4.009 passed, 2 skipped, 12 errors, 60s; sockets localhost bloqueados |
| FAIL | pytest tests/ -q com mocks localhost permitidos | 125 failed, 4.087 passed, 2 skipped, 172,23s; zero erros de execução |
| FAIL histórico | CI do PR #797 | jobs principais falharam; logs consultados de runs 38048147190, 38048147222 e 38048147215 |
| NOT RUN | CI do novo SHA remoto | será consultado após push/PR; nenhum sucesso remoto inferido dos testes locais |
| NOT APPLICABLE | merge/deploy/hardware real | nenhuma dessas operações autorizada ou executada |

O servidor de QA usa banco `/tmp/c65-recovery-frontend.sqlite`, credencial fixa de teste e import WSGI em localhost sem start_background_threads. Nenhum worker externo, pool, pagamento, compra ou comando físico foi ativado. `run-e2e.sh` foi inspecionado; a execução equivalente usa Playwright contra esse servidor isolado, porque o worktree não possui venv próprio.

Logs locais: `/tmp/c65-recovery-js.log`, `/tmp/c65-recovery-series-tests.log`, `/tmp/c65-recovery-e2e-final.log`, `/tmp/c65-recovery-frontend-final.log`, `/tmp/c65-recovery-pytest-unsandboxed.log`. São evidência da sessão, não artefatos permanentes de CI.

## 5. /devil findings

Revisão independente por subagente /devil, somente leitura; não equivale a GitHub approval.

| Severidade | Equipe | Evidência | Situação |
|---|---|---|---|
| HIGH | Frontend | vm do fonte reproduziu [111] antigo depois de [222] recente | corrigido e regression test |
| MEDIUM | Frontend | canvas substituído mantinha chart/handlers antigos | destroy + afterDestroy cleanup + teste |
| HIGH | QA | assert de limpeza de circles no logout havia sido removido | restaurado e E2E passou |
| MEDIUM | QA | assertions de primeira dobra haviam sido removidas | restauradas; HTML estrutural corrigido; E2E passou |
| MEDIUM | Frontend | resposta 402/JSON atrasada podia resetar range atual | corpo/estado revalidados e teste |

O review não encontrou novo CRITICAL/HIGH no escopo final revisado; gates externos e achados da base continuam bloqueantes.

## 6. /advisor recommendations

Segunda opinião independente por subagente, leitura do código e WIPs; não executou testes.

**Problema → alternativas → riscos → recomendação → justificativa → aceite:**

- Frontend: reparo local versus reescrever dashboard. Refatoração ampliaria superfície. Escolhido reparo de ownership/epochs e DOM; aceite: fontes reais, canvas único, async inverso, firstfold e logout.
- Overview: ocultar versus atualizar teste. #797 já tornou overview visível; teste alinhado a visible/aria-busy=false, preservando os contratos de layout/isolamento.
- Fleet: recuperar primitives versus incorporar WIP de 850–971 linhas adicionadas. WIP muda identidade, restore, agente e telemetria; escolhido hotfix #799 separado, Refs #777, com restore inválido sem mutação.
- Mobile: instalação tolerante versus árvore determinística. Escolhido #800 com peers estritos, npm ci/npm ls/Doctor/lint/typecheck/Jest/exports. React sozinho não explica o erro: o peer react-reconciler ^19.3.0 está no lock.

## 7. Dívida técnica priorizada e auditoria CYPHER65

| Prioridade | FATO / limite | Próximo passo |
|---|---|---|
| P0 | CI transversal bloqueia integração; Bandit encontrou SQL composto em registry | #799, parametrização clara e gates estáticos |
| P1 | Fleet chama normalizer/classe sem definição/imports; 99 NameErrors no run inicial | recuperar primitives e testar restore, sem alterar histórico real |
| P1 | restore compara dois MACs inválidos como None==None após reintroduzir helper | exigir ambos válidos e iguais dentro da transação |
| P1 | contrato/fallback AxeOS e discovery também falham | reproduzir separadamente após recuperar primitives; sem hardware |
| P1 | árvore mobile CI tem React invalid e WASM extraneous | #800, instalação limpa e compatibilidade Expo/Babel |
| P2 | MF-005 sem link de teste na matriz | provar cobertura relevante; acrescentar marker, nunca dispensar gate |
| P2 | #787 aberta embora #793 e testes focados cubram parte do mesmo escopo | triagem por critérios, sem fechamento manual por PR aberto |
| P2 | #777 WIPs de identidade são maiores que hotfix | manter isolados e executar corrida SQLite/tenants/tombstones antes de integração |

**Fleet Discovery:** existem manual add, Agent outbound e tombstones, mas primitives ausentes impedem prova de registro íntegro. LAN não foi acessada. **Telemetria:** testes verificam zero/ausência/stale; fixture não prova sensor físico ou conectividade. **Rentals:** contrato versus amostras/cobertura é separado; hashrate contratado não é entrega comprovada. **Probability:** testes focados passam para Poisson/unidades/unknown; probabilidade não é prazo. **Commands:** nenhuma alteração ou execução real; garantias físicas/ACK/rollback permanecem sem validação física. **Segurança/tenants:** E2E de logout preservado; testes globais Fleet falham, logo isolamento global não é declarado aprovado.

O inventário GitHub encontrou 13 Issues abertas. Além do recovery: #757 (unificação UX), #659 (BTC PoW Lab, PR #715 existente), #606/#607 (escala/ingestão), #600 (faixas de custo), #598 (payout), #399 (iOS epic), #386 (matriz física), #330 (pagamento em produção), #22 (Postgres gated). Essas funcionalidades requerem validação e escopo próprios; não foram implementadas como efeitos colaterais do reparo frontend. Ativação de pagamentos, produção e hardware permanece fora desta execução.

## 8. Merge readiness

#798: validado localmente e revisável; bloqueado para merge até CI do SHA exato verde e approval externo. #799/#800: unidades de recuperação em progresso com Issues próprias. #797: já integrado historicamente com falhas, sem nova autorização. Nenhum merge/deploy será realizado nesta tarefa.

## 9. Next actions

1. Publicar PR #798 com evidência e observar os checks do SHA enviado.
2. Recuperar primitives Fleet/restore em #799, reexecutar testes e reduzir falhas por causa demonstrada.
3. Recuperar a árvore mobile em #800 e validar sem mascarar peers.
4. Corrigir falhas AxeOS/MF-005 remanescentes em unidades próprias.
5. Registrar reviews/gates finais; obter aprovação humana independente antes de qualquer integração.
