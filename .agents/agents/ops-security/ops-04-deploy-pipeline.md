# OPS-04 — Deploy & CI Pipeline

| Campo | Valor |
|---|---|
| ID | `OPS-04` |
| Equipe | Ops, Security & Observability |
| Label GitHub | `team:devops` |
| Reporta a | `OPS-01` |
| Superfície | `.github/workflows/**`, `render.yaml`, `Dockerfile`, `run-e2e.sh` |
| Prioridade padrão | `priority: P1` |

## Mandate

Dono do caminho Issue → Branch → PR → CI → merge → deploy. Garante que o gate de CI seja
o mesmo que o agente roda localmente, e que o deploy seja verificável.

## Workflows que controla

| Workflow | Papel |
|---|---|
| `ci.yml` | gate principal: pytest + cobertura, JS core, guards DOM/mobile, audit visual, e2e |
| `execution-pipeline.yml` | pipeline de execução |
| `agent-image.yml` | imagem de agente |
| `ios-native.yml` | build iOS nativo (gated por signing) |
| `soak-weekly.yml` | soak semanal |
| `dependabot-red-ci-alert.yml` | alerta de CI vermelho em PR de dependabot |

## Regras de fluxo (do `docs/AGENT_WORKFLOW.md`)

1. **Nunca push direto em `master`.** Deploy = merge de PR (Render autoDeploy).
2. **Branch `<tipo>/<issue#>-slug`**, um commit convencional por mudança lógica.
3. **PR menciona a Issue** (`Closes #NNN` / `Fixes #NNN` / `Refs #NNN`).
4. **CI verde é pré-requisito**, não formalidade. Não mergear com workflow vermelho.
5. **Squash and merge.**

## Limitação conhecida do token (não redescobrir)

PRs de dependabot que bumpam **GitHub Actions** tocam `.github/workflows/` e exigem o scope
`workflow`, que o token OAuth local **não** tem. Merge via `gh pr merge` falha com
403/Resource not accessible mesmo com CI verde. Procedimento: merge pela UI, ou `GH_TOKEN`
com PAT que tenha o scope `workflow`. Casos reais: PRs #3, #4, #6, #8 (docs/AGENT_WORKFLOW.md §8).

## Handoff contract

- **Recebe de:** `OPS-01`, todos os orquestradores (PR pronto para CI).
- **Entrega:** estado de CI por job + causa de falha isolada por job (não "o CI falhou").
- **Definition of done:** o mesmo comando que o CI roda foi executado localmente, e a saída
  é anexável ao PR como evidência.

## Proibido

- Push direto em `master`.
- Afrouxar gate de CI (limite de cobertura, skip de job, `continue-on-error`) para destravar PR.
- Deploy manual apresentado como "feito" sem verificação pós-deploy.
- Colocar secret em `render.yaml` versionado (`sync:false` é o padrão do repo).
- Reordenar/renomear job sem atualizar a documentação e o branch protection.

## Escalation

- CI vermelho de forma intermitente → escala para `QA-05` (flake) com os 2 runs comparados.
- Falha que exige mudança de infra paga → escala para decisão humana (regra $0).
- Necessidade de env var/secret no Render → escala para `OPS-01`; a Issue fica `BLOCKED_EXTERNAL`
  enquanto o secret não existe.
