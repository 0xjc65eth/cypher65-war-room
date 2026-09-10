# Governança de merge

O ruleset ativo do GitHub `Protect main and release branches` protege
`master` e `release/**`. Sua configuração versionada está em
`.github/rulesets/master-protection.json`.

## Controles obrigatórios

- Todo merge passa por pull request com pelo menos uma aprovação.
- O único método permitido nas branches protegidas é squash merge.
- Novos commits invalidam aprovações existentes.
- Todas as conversas de review devem estar resolvidas.
- A branch do PR deve estar atualizada em relação à base.
- **Bypass administrativo (break-glass, Issue #482):** existe um único actor
  de bypass — `RepositoryRole: Admin`, `bypass_mode: pull_request` — capaz de
  fazer merge admin em PRs nas branches protegidas (ex.: deadlock de
  auto-approval do único maintainer, caso das PRs #479/#480). O bypass é
  restrito a merges de PR: deleção e non-fast-forward continuam bloqueadas
  para todos. Regra de uso: merge admin apenas com CI 100% verde e a
  justificativa registrada na descrição do PR. Qualquer mudança neste actor
  passa por Issue + PR neste arquivo.
- Deleção e atualização non-fast-forward das branches protegidas são
  bloqueadas.

## Status checks exigidos

Os nomes abaixo são os contextos emitidos pelos jobs dos workflows. Renomear
um job exige atualizar o ruleset no mesmo fluxo de mudança.

| Workflow | Contexto obrigatório |
|---|---|
| `Soak Test · CI` | `Unit Tests` |
| `CI · Gate` | `pytest + JS core` |
| `CI · Gate` | `mobile: lint + typecheck + jest + build` |
| `CI · Gate` | `frontend: audit visual + guards` |
| `CI · Gate` | `e2e: playwright chromium` |
| `🚀 Execution Pipeline` | `validate` |
| `🚀 Execution Pipeline` | `build-image` |
| `🚀 Execution Pipeline` | `integration` |

## Aplicar e verificar

Requer permissão administrativa no repositório. Confirme o ID atual antes de
aplicar; no momento da Issue #443 ele era `20918386`.

```bash
gh api --method PUT \
  repos/0xjc65eth/cypher65-war-room/rulesets/20918386 \
  --input .github/rulesets/master-protection.json

gh api repos/0xjc65eth/cypher65-war-room/rulesets/20918386 \
  --jq '{enforcement, bypass_actors, current_user_can_bypass, conditions, rules}'
```

Valide a aplicação com um PR sem review. Enquanto ele não tiver uma aprovação
válida e todos os contextos acima não estiverem verdes, o GitHub deve reportar
`mergeStateStatus: BLOCKED` e `reviewDecision: REVIEW_REQUIRED`.

```bash
gh pr view NUMERO \
  --json mergeable,mergeStateStatus,reviewDecision,reviews,statusCheckRollup
```
