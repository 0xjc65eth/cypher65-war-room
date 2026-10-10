# Série PR1–PR7 — recuperação verificada em 2026-10-10

Ordinais funcionais, não números literais do GitHub. Base consultada ao vivo: `master`, `155dcc7a0ce9e725a54e06bba291932a5b8793a4`.

| Etapa | Objetivo | Issue | PR GitHub | Branch | Head / squash | Estado | Testes atuais | Dependência / próxima ação |
|---|---|---|---|---|---|---|---|---|
| PR1 | Proveniência de rede | #776 | [#784](https://github.com/0xjc65eth/cypher65-war-room/pull/784) | `pr/1-provenance-network-hashrate` | `d314ec3f12d6` / `7699b113b79a` | Complete integrado; readiness global Partial | `tests/test_hashrate_market.py` no run agregado de 407 PASS | Nenhuma recriação; depende dos gates comuns |
| PR2 | Block Probability Lab | não declarada | [#785](https://github.com/0xjc65eth/cypher65-war-room/pull/785) | `pr/2-block-probability-lab` | `e253cee423b5` / `b653478ae075` | Complete integrado; readiness global Partial | `tests/test_block_probability_lab.py` no run agregado de 407 PASS | Corrigir rastreabilidade em manutenção; depende dos gates comuns |
| PR3 | Session Evidence | #792; Refs #787 | [#786](https://github.com/0xjc65eth/cypher65-war-room/pull/786) | `pr/3-session-work` | `497e4688d918` / `7e4e83e881ad` | Complete integrado; readiness global Partial | `tests/test_session_evidence.py` no run agregado de 407 PASS | #793 completa PR3; #787 requer triagem; depende dos gates comuns |
| PR4 | Cenários econômicos | #788 | [#794](https://github.com/0xjc65eth/cypher65-war-room/pull/794) | `feat/788-economic-scenarios` | `298654ff3041` / `e4cf9a9329d0` | Complete integrado; readiness global Partial | `tests/test_economic_scenario_matrix.py` no run agregado de 407 PASS | Preservar modelos normalizados; depende dos gates comuns |
| PR5 | Hash Market intelligence | #789 | [#795](https://github.com/0xjc65eth/cypher65-war-room/pull/795) | `feat/789-hashpower-intelligence` | `797feaa25a60` / `f41677ad9971` | Complete integrado; readiness global Partial | `tests/test_market_intelligence.py` no run agregado de 407 PASS | Preservar freshness/ranking; depende dos gates comuns |
| PR6 | Rental delivery evidence | #790 | [#796](https://github.com/0xjc65eth/cypher65-war-room/pull/796) | `feat/790-rental-delivery-evidence` | `64dab6b6f31b` / `ec3bdf6b8549` | Complete integrado; readiness global Partial | `tests/test_rental_performance.py` no run agregado de 407 PASS | Preservar zero versus ausência; depende dos gates comuns |
| PR7 | Operations evidence overview | #791 | [#797](https://github.com/0xjc65eth/cypher65-war-room/pull/797) | `feat/791-evidence-operations-overview` | `9c9585aa2b0d` / `155dcc7a0ce9` | Complete integrado; readiness global Partial | `tests/test_command_center.py` no run agregado de 407 PASS | Reparar gates transversais; depende dos gates comuns |

## Complementos e limites

- [#793](https://github.com/0xjc65eth/cypher65-war-room/pull/793), branch `fix/792-session-evidence`, head `b0ad9fc25f0b`, squash `d1871f59d684`, é complemento de PR3, não PR4.
- A [Issue #787](https://github.com/0xjc65eth/cypher65-war-room/issues/787) continua aberta. Os testes focados de Session Evidence passam; abertura de PR ou mapeamento não autoriza fechamento manual.
- PR2 não declara Issue no corpo consultado. Números previstos no plano antigo não são associação comprovada.
- PR #797 está MERGED desde 2026-10-10, mas seu rollup registra FAILURE em pytest/JS, Unit Tests, validate, mobile, frontend e E2E. Não há review approval no snapshot consultado. Isso é um fato histórico de integração, não autorização de merge nesta recuperação.
- A Issue #798 trata frontend; #799 recupera primitives Fleet referenciados pelo código integrado; #800 trata árvore mobile. Não recriar PRs já integrados.
- Evidência atual: `RECOVERY_REPORT.md`. Merged e testes focados não provam produção saudável, conectividade ASIC/pool ou todos os gates verdes.
