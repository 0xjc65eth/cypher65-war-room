# Recovery #803 — Black25.1.0

Sete arquivos integrados em PR1–PR7 quebravam gate Black na master155dcc7: app.py, helpers.py, routes/block_probability_lab_routes.py, services/block_probability_lab.py,services/hashrate_market.py,services/poll_compute.py,services/proximity.py. Aplicado apenas Black25.1.0.

AST antes/depois idêntica nos sete arquivos (sem atributos de posição);407testes focados PR1–PR7PASS4.20s. Nenhuma mudança funcional. Black global neste checkout ainda reporta registry/routes Fleet preexistentes; reparados separadamente naIssue799. Combinação deve passar; nenhuma tolerância adicionada ao gate. diff--checkPASS. CI no novoSHA pendente, sem merge/deploy.
