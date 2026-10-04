## Falha de inicialização publicada — diagnóstico somente leitura

2026-10-04. FATO: navegador público registrou `SyntaxError: Unexpected token ')'` em `/static/app.js?v64`; relógio, navegação e carregamento de dados não inicializam. `node --check` reproduziu no bundle público e no bundle de master d2e0a57 (linha 15157). SHA256 público 15f5f48843548e6f781f4b4416c990c9c8e78cb0e34abc7d0503c2182c7118bf; bytes iguais a master.

FATO: o diff de #755 sobre eb5664b reintroduziu cinco linhas de `consoleNumber` sem fechar a função, um return de telemetria anterior ao retorno com bounds e um `if (!row) return` anterior ao fechamento do diálogo. O snapshot público respondeu com contexto da rede e pool; healthz ok/cloud true. API alcançável não prova ASIC ou credenciais de terceiros.

RECOMENDAÇÃO: remover somente os sete resíduos de merge, preservar as correções #751, regerar app.js. Aceite: parse/drift, JS core e E2E navegação + console desktop/mobile; CI do novo head e review antes de merge. Nenhum comando físico, pagamento ou secret consultado.

Limitação: este diagnóstico explica o bloqueio global atual; a auditoria de todas as funções e o benchmark visual seguem após a restauração do boot. Implementação autorizada pela solicitação original de correção e continuidade da sessão, em Issue/branch/PR separado.

### Resultado local da correção

Removidos somente sete resíduos no fragmento 39b; app.js regenerado. Restaurado fechamento perdido do teste de login/logout em #753. Asserção antiga dos KPIs foi substituída por quatro métricas visíveis da operação e contexto global separado, incluindo abrir o disclosure mobile.

Parse/drift/diff PASS; JS core 1.669 PASS; frontend completo PASS, axe zero violações desktop/mobile. Rodada de 114 E2E: 112 PASS e dois FAIL da asserção antiga de KPI escondido; após corrigir o contrato do teste, reexecução dos dois cenários PASS. Sem afirmação de CI ou produção corrigida nesta fase.
