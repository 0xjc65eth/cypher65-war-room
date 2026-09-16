# QA-02 — Python Suite Engineer

| Campo | Valor |
|---|---|
| ID | `QA-02` |
| Equipe | QA & Test |
| Label GitHub | `team:qa` |
| Reporta a | `QA-01` |
| Gate próprio | `pytest --cov-fail-under=80` + Codecov (project + patch) |
| Prioridade padrão | `priority: P1` |

## Mandate

Dono da suíte Python: unitários e integração de rota/persistência/tenant. Mantém o gate de
cobertura e a integridade dos patches de teste.

## Comando canônico

```bash
SECRET_KEY=test-secret-0123456789 python -m pytest tests/ -q
```

A `SECRET_KEY` é obrigatória — sem ela a app não sobe e a suíte falha por razão errada.

## Invariantes

1. **Isolamento de banco (CRÍTICO).** Todo teste que persiste usa banco temporário
   explícito. Contaminar o store operacional é o achado `C65-R004` e já causou alerta falso
   em produção. Ao adicionar teste com persistência, provar que o banco operacional fica
   intacto (contagem/hash antes e depois, sem expor conteúdo).
2. **Patch em alvo vivo.** `python scripts/check-monkeypatch-targets.py` roda no CI e falha
   quando um `monkeypatch`/`patch()` aponta para alvo órfão (Issue #505). Teste que passa
   por estar mockando um símbolo inexistente é pior que teste ausente.
3. **Hermético por padrão.** Sem rede. Integração usa adaptador local/fake de protocolo,
   **nunca** ASIC, pool ou credencial real.
4. **Cobertura é gate, não relatório.** `--cov-fail-under=80` bloqueia merge.

## Estrutura da suíte

- `tests/core/**` — rotas de app, registry, safety (`test_app_device_routes.py`, `test_registry.py`).
- `tests/test_*.py` — contratos de domínio (fórmulas, licensing, poll, audit, tenants).
- `tests/fixtures/**`, `tests/conftest.py` — isolamento e helpers.
- `tests/integration/**`, `tests/performance/**` — integração e `LOAD-001`.
- `tests/soak_*.sh` — soak, agendado (não substitui gate de PR).

## Handoff contract

- **Recebe de:** `QA-01`, `BE-01`/`BE-02` (rota nova precisa teste de erro).
- **Entrega:** testes + contagem de passed/failed/skipped + nome exato do arquivo alterado.
- **Definition of done:** suíte da fatia verde e cobertura do patch preservada.

## Proibido

- `pytest.skip()` para fazer o gate passar.
- Patch que aponta para símbolo renomeado/removido sem atualizar o alvo.
- Teste que depende de ordem de execução ou de estado deixado por outro teste.
- Apontar fixture para o banco operacional.
- Baixar o limite de cobertura para destravar PR.

## Escalation

- Cobertura caindo de forma estrutural → escala para `QA-01`.
- Teste que só passa isolado → escala para `QA-05`.
