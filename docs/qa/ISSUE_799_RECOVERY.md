# Recovery #799 — integridade de identidade Fleet

Base155dcc7;2026-10-10. Refs #777. Hotfix limitado; não incorpora os WIPs completos nem migra/combina registros históricos.

Causas comprovadas: normalize_device_mac/DeviceIdentityConflict chamados mas ausentes; active_only usado sem parâmetro; SQL composto bloqueando Bandit; refresh de capacidades exigia campo capabilities em vez de type/firmware. Restore comparava MACs inválidos como None==None. Manual add apagava tombstone antes de sondar, perdendo identidade/histórico e deixando alias órfão. Cloud add anunciava restore sem evidência e enfileirava caminho rejeitado pelo agente. GC/hard delete também deixavam aliases órfãos; GC selecionava candidatos antes do lock de escrita.

Reparo: MAC unicast válido normalizado (malformado/zero/multicast é unknown), classe/imports restaurados, active_only explícito, SQL fixo parametrizado. Restore verifica ambosMACs em BEGIN IMMEDIATE e conserva ID/histórico/aliases; add removido retorna409 antes de probe/fila, em outroIP a mesmaMAC removida também não ressuscita. GC trava antes da seleção e elimina somente aliases correspondentes no mesmo commit, com rollback; hard delete também mantém integridade transacional. Refresh atualiza last_seen/agent_managed e recomputa capacidades de discovery conhecida.

Três testes API antigos foram alinhados ao contrato seguro: MAC explícita; preservação do mesmoID e telemetria; probe outbound apenas depois de restore. Nenhuma assertion de segurança foi dispensada. Teste de fallback recebeMAC conhecida para atingir polling; guard semMAC permanece.

Validação observada: 127PASS em testes/test_agent_api.py + identidade35 + GC7,2.45s; SQLite temporário, fixtures/mocks, sem hardware. Review independente /devil reproduziu perda de row/alias e GC, revisou reparo add/restore, rodou42tests; autor principal revisou diffs GC e rollback/tenant/concurrency tests. Isso não é GitHub approval.

Bandit -ll:0medium/high; Flake8:PASS; Black nos dois arquivos:PASS; diff:PASS. Black global ainda falha em sete arquivos preexistentes (Issue803). Suite global após primitives iniciais:21failed/4191passed/2skip; fixtures/traceability separadas em802. Primitives iniciais já reduziram125falhas para21, mas isso não representa readiness global.

Logs /tmp/c65-799-focused.log, /tmp/c65-fleet-identity-tests.log, /tmp/c65-fleet-recovery-pytest.log e gates estáticos da sessão. CI do SHA exato deve ser observado. Sem dados reais alterados, comandos físicos, merge ou deploy. Registros históricos já órfãos continuam fail-closed; não há correção destrutiva automática. #777 permanece escopo maior.
