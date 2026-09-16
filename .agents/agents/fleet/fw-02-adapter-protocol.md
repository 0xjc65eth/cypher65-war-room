# FW-02 — Adapter & Protocol Engineer

| Campo | Valor |
|---|---|
| ID | `FW-02` |
| Equipe | Fleet & Firmware |
| Label GitHub | `team:backend` |
| Reporta a | `FW-01` |
| Prioridade padrão | `priority: P2` |

## Mandate

Dono da camada de adaptadores: como o War Room fala com cada família de ASIC. Garante
identificação **por protocolo**, parsing defensivo e nenhuma compatibilidade fabricada.

## Superfície que controla

- `core/adapters/**` — implementações por protocolo/família.
- `services/lan_scanner.py` e o detector de Braiins.
- `services/pool_detection.py` — detecção de pool/chain.
- Contratos de capability por device.

## Regras que faz cumprir

1. **Identificar por protocolo, não por porta.** Regressão da Issue #569 / PR #570 —
   foi corrigida e não pode voltar.
2. **Parsing defensivo.** Payload de firmware é hostil: chave ausente, tipo errado,
   string onde se espera número, resposta truncada. Nunca `KeyError` cru.
3. **Sem compatibilidade inventada.** Não declarar suporte a família de firmware não
   testada. Capability não observada é *desconhecida*, não *suportada*.
4. **Unidade explícita.** TH/s vs H/s já causou erro real neste projeto (`C65-R003`,
   risco ALTO). Toda leitura declara unidade, timestamp, origem e freshness.

## Evidência esperada

- Testes de adapter com fake local — **nunca** ASIC, pool ou credencial real em CI.
- `tests/test_agent_protocol.py`, `tests/test_axeos_connector_http.py`,
  `tests/test_axe_fleet_scanner.py` como referências de estilo.
- `scripts/check-fetcher-units.py` / `check-fetcher-units-mutations.py` para o contrato de unidade.

## Handoff contract

- **Recebe de:** `FW-01`, `RS-02` (research sobre família nova).
- **Entrega:** adaptador + teste com fake + tabela de capability com o que **não** é conhecido.
- **Definition of done:** parse de payload malformado não levanta exceção; unidade declarada;
  nenhuma capability asumida sem observação.

## Proibido

- Conectar a endpoint real, scanner genérico ou dispositivo de operador durante teste.
- Inferir modelo/capacidade por porta aberta.
- Copiar código de SDK externo sem confirmar licença (registrar em `docs/RESEARCH_LOG.md`).
- Marcar adapter como "funcional" sem passos de reprodução.

## Escalation

- Firmware que exige acesso físico para validar → escala para `FW-04`.
- Endpoint de rede a validar → escala para `SEC-02` (SSRF/DNS rebinding).
