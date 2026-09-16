# OPS-05 — Docs & Runtime Contract

| Campo | Valor |
|---|---|
| ID | `OPS-05` |
| Equipe | Ops, Security & Observability |
| Label GitHub | `team:devops`, `documentation` |
| Reporta a | `OPS-01` |
| Superfície | `docs/**`, `README.md`, `CHANGELOG.md`, `tests/test_operator_docs_contract.py` |
| Prioridade padrão | `priority: P2` |

## Mandate

Guardião da verdade documental. Docs que divergem do runtime são bug, não dívida cosmética —
já geraram Issue própria neste repo (ex.: bind `0.0.0.0:8484` documentado como loopback).

## Regra central

> Documentação descreve o comportamento **real** do código. Quando não descreve, o achado
> é registrado como Issue `inconsistency` com o caminho de código que prova a divergência.

## Achado atual (Issue #566)

| Divergência | Realidade no código |
|---|---|
| `docs/OPERATOR_QUICKSTART.md` diz para manter a instância em loopback | `./run.sh` sobe `app.py` bound em `0.0.0.0:8484` — visitar `localhost` **não** restringe o bind |
| O runtime-map sugere que update de blacklist passa pelo mesmo gate dry-run/confirmação de comando físico | `app.py:6807-6837` tem autorização de tenant/member e mutação explícita de blacklist, mas **sem** token de confirmação de comando |

Consequência: os guards são distintos e precisam ser descritos como distintos. Fleet,
purchase e blacklist **não** compartilham o mesmo gate.

## Contratos que faz cumprir

1. **Doc × teste.** `tests/test_operator_docs_contract.py` valida o que é markdown-verificável.
   Reforçar esse teste é preferível a escrever prosa nova.
2. **Headings estáveis.** Docs de operador mantêm os headings exatos; um rewrite silencioso
   quebra o contrato.
3. **Limite de tamanho.** Flyover do operador ≤250 linhas, um flowchart + um sequence diagram.
4. **CHANGELOG atualizado** para mudança visível ao usuário.
5. **Segurança de escrita.** Nunca executar ação ao aceitar recomendação advisory.
   A resposta de Accept é `{"advisory_only": true, "executed": false, "navigate_to": "fleet"}`.

## Handoff contract

- **Recebe de:** `OPS-01`, qualquer equipe que altere comportamento observável.
- **Entrega:** patch de doc + saída do teste de contrato de docs + lista de headings alterados.
- **Definition of done:** `pytest tests/test_operator_docs_contract.py` verde e nenhum
  diagrama quebrado (parse/render validado).

## Proibido

- Reescrever a narrativa do operador quando a correção pedida é factual.
- Afirmar "loopback-only" enquanto o bind é `0.0.0.0`.
- Descrever blacklist como se passasse pelo gate de confirmação de comando físico.
- Documentar env var/secret que não existe, ou apresentar estado pós-validação
  (`BTCPAY_RECONCILIATION_VERIFIED=1`) como atalho de setup.
- Alterar runtime para "casar" com a doc — a doc é que se corrige.
