# Recovery #800 — árvore mobile compatível com Expo 57

Base master155dcc7; 2026-10-10. Antes: npm ci concluía com warnings, mas npm ls --all falhava: test-renderer1.3 exigia react-reconciler0.34/React19.3, incompatível com React19.2.8. Typescript7 acrescentava árvore nativa/optional extraneous. Expo Doctor20/21 reportava oito desalinhamentos.

package.json segue versões verificadas pelo Doctor: React19.2.3, Expo57.0.27, preset57, Jest29.7, Typescript6.0.3, test-renderer1.2.0. Stryker core/runner9.6.1 mantém Babel7 e timeoutMS existente. Nenhum peer tolerado com --force/legacy-peer-deps.

Lock regenerado. Override forge permanece no commit ceba34402e329f0365134f23fe19898756527d65 com HTTPS; braces permanece tarball vendorizado/integridade original. shell-quote1.12.0 e smol-toml1.9.1 corrigem advisories já presentes na base, dentro dos ranges existentes. Instalação estrita limpa após essas mudanças confirmou árvore válida.

| Gate | Resultado |
|---|---|
| npm ci --strict-peer-deps --legacy-peer-deps=false | PASS; 911 pacotes |
| npm ls --all | PASS; sem invalid/extraneous |
| Expo Doctor | PASS;21/21 |
| Biome / TypeScript | PASS;30 arquivos / sem erros |
| Jest | PASS;16 suites,111 tests |
| Expo export iOS/Android/Web | PASS; três exports |
| security-node-forge | PASS; forgery rejeitada e RSA válido |
| security-braces | PASS; provenance/runtime/depth e10testes de adulteração |
| npm audit --audit-level=high | PASS;zero high/critical,22moderate remanescentes na cadeia sprintf-js/Jest |
| diff --check | PASS |

Logs locais de sessão: /tmp/c65-mobile-final-doctor.log e /tmp/c65-advisor-{ci,tree,forge,braces,audit,jest,build,lint,types}.log. Não equivalem a gates do novo SHA no Linux. Npm não verifica integrity de dependências Git; pin de commit e vetores funcionais preservados. Exports não certificam runtime nativo nem dispositivos físicos. Mutação: NOT RUN, nenhuma lógica de aplicação alterada.

Revisão estratégica independente /advisor confirmou compatibilidade e corrigiu advisories sem relaxar guards. Revisão adversarial /devil será registrada no relatório geral. Não houve merge/deploy.
