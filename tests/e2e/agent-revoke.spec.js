/**
 * CYPHER65 War Room — E2E: REVOKE AGENTS (Issue #582)
 * ==================================================
 *
 * Prerequisites: Flask server running on BASE_URL (default http://127.0.0.1:8765)
 *
 * Run:  npx playwright test tests/e2e/agent-revoke.spec.js --project=chromium --workers=1
 *
 * Covers, contra o servidor REAL (nada de `page.route` — a rota de revogação
 * é exercitada de verdade, senão o teste só provaria que o mock funciona):
 *   - Duas etapas: o gatilho NÃO revoga sozinho; a consequência aparece antes
 *     da ação (nada de `window.confirm()`, que pergunta sem explicar)
 *   - Confirmar revoga de verdade e o painel assume o sucesso SÓ com o 200
 *   - Em `done` a linha do token SAI da tela — é credencial morta ao lado de
 *     um comando de instalação; deixá-la visível convida ao erro
 *   - Falha (500) mantém a confirmação aberta com o botão de tentar de novo,
 *     nunca "sucesso"
 *   - Recusa (403) diz o MOTIVO e NÃO oferece retry (Issue #586): revogar
 *     exige `admin`, e repetir o clique não muda o seu papel
 *
 * O servidor de e2e roda em modo self-host (sem flag de nuvem), então a
 * revogação é permitida no modo aberto — o gate de identidade da nuvem está
 * coberto por unidade (`test_agent_token_revocation.py`). As recusas de 403 são
 * forçadas com `page.route`, o MESMO precedente do caso de 500: o alvo é a
 * reação da UI, não o servidor.
 */

import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';

/** App shell pronto (skeletons fora, boot sincrono terminado). */
async function waitForDashboard(page) {
  await page.waitForSelector('#app-shell', { timeout: 15000 });
  await page.waitForFunction(() => {
    return document.querySelectorAll('.skel-overlay').length === 0;
  }, { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(600);
}

/** Mobile: a sidebar é off-canvas — sem abrir, o link do módulo não é clicável. */
async function ensureSidebarOpen(page) {
  const isOpen = await page.evaluate(() => {
    const sb = document.getElementById('sidebar');
    return sb && sb.classList.contains('open');
  });
  if (!isOpen) {
    const toggle = page.locator('#sidebar-mobile-toggle');
    if (await toggle.isVisible()) {
      await toggle.click();
      await page.waitForTimeout(400);
    }
  }
}

/** Abre o painel do agente (Fleet → CONNECT AGENT). */
async function openAgentPanel(page) {
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
  await waitForDashboard(page);
  // O painel do Fleet é um módulo da sidebar: sem navegar até ele, o botão
  // existe no DOM e não está visível (o `#app-shell` sozinho não o mostra).
  await ensureSidebarOpen(page);
  await page.locator('.sidebar__link[data-module="fleet"]').click();
  await expect(page.locator('#axe-fleet-panel')).toBeVisible({ timeout: 8000 });
  await page.click('#axe-agent-btn');
  await expect(page.locator('#axe-agent-panel')).toBeVisible({ timeout: 5000 });
  await expect(page.locator('#axe-revoke-open')).toBeVisible({ timeout: 5000 });
}

test('o gatilho sozinho não revoga: mostra a consequência antes', async ({ page }) => {
  await openAgentPanel(page);

  const confirm = page.locator('#axe-revoke-confirm');
  await expect(confirm).toBeHidden();

  await page.click('#axe-revoke-open');

  // A confirmação aparece com o que vai PARAR de funcionar, e com a saída.
  await expect(confirm).toBeVisible();
  await expect(page.locator('#axe-revoke-title')).toHaveText(/REVOGAR TODOS OS AGENTES/);
  await expect(page.locator('#axe-revoke-body')).toContainText('para de enviar telemetria');
  await expect(page.locator('#axe-revoke-body')).toContainText('CYPHER65_AGENT_TOKEN');
  await expect(page.locator('#axe-revoke-do')).toBeEnabled();
  // O gatilho sai de cena: com a confirmação aberta, não há dois caminhos.
  await expect(page.locator('#axe-revoke-open')).toBeHidden();

  // Desistir volta ao repouso sem tocar no servidor.
  await page.click('#axe-revoke-cancel');
  await expect(confirm).toBeHidden();
  await expect(page.locator('#axe-revoke-open')).toBeVisible();
});

test('onboarding renders and copies a valid Docker command (#636)', async ({ page }) => {
  // UI contract: token issuance is stubbed; no real credential or install.
  await page.route('**/api/agent/token', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ token: 'test.jwt.token', server_url: 'https://dashboard.example/', tenant_id: 'fixture' }),
  }));
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: async text => { window.__copiedAgentCommand = text; } },
    });
  });
  await openAgentPanel(page);
  await page.click('#axe-agent-gen');
  await expect(page.locator('#axe-agent-token-row')).toBeVisible();
  const command = await page.locator('#axe-agent-docker').textContent();
  expect(command.split('\n')).toHaveLength(5);
  expect(command).not.toContain('\\n');
  expect(command).toContain("CYPHER65_SERVER_URL=https://dashboard.example'");
  expect(command).toContain("CYPHER65_AGENT_TOKEN=test.jwt.token'");
  await page.click('#axe-agent-copy-docker');
  await expect.poll(() => page.evaluate(() => window.__copiedAgentCommand)).toBe(command);
});

test('confirmar revoga de verdade, UMA vez, e assume o sucesso só com o 200', async ({ page }) => {
  await openAgentPanel(page);

  const posts = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/agent/tokens/revoke') && r.method() === 'POST') posts.push(r);
  });
  const revoked = page.waitForResponse(
    (r) => r.url().includes('/api/agent/tokens/revoke') && r.request().method() === 'POST',
    { timeout: 15000 },
  );

  await page.click('#axe-revoke-open');
  await page.click('#axe-revoke-do');

  const resp = await revoked;
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.success).toBe(true);

  // O painel mostra os epochs que o SERVIDOR devolveu, não um otimista.
  await expect(page.locator('#axe-revoke-title')).toHaveText(/REVOGADO/, { timeout: 8000 });
  await expect(page.locator('#axe-revoke-status')).toContainText(
    `epoch ${body.revoked_epoch} → ${body.active_epoch}`,
  );
  await expect(page.locator('#axe-revoke-status')).toHaveAttribute('data-tone', 'ok');
  await expect(page.locator('#axe-revoke-do')).toBeDisabled();

  // A credencial exibida morreu: a linha inteira sai da tela.
  await expect(page.locator('#axe-agent-token-row')).toBeHidden();

  // UM clique = UM POST. Dois disparos incrementariam o epoch duas vezes — e
  // invalidariam também o token que o usuário acabou de gerar.
  await page.waitForTimeout(1200);
  expect(posts.length).toBe(1);
});

test('um 500 mantém a confirmação aberta com tentar-de-novo (nunca sucesso)', async ({ page }) => {
  await openAgentPanel(page);

  // Força a falha no fetch de revogação — o caminho que o servidor de e2e não
  // produz. Aqui o mock é legítimo: o alvo é a REAÇÃO da UI ao erro.
  await page.route('**/api/agent/tokens/revoke', (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ success: false, error: 'não consegui registrar', detail: 'database is locked' }),
    }),
  );

  await page.click('#axe-revoke-open');
  await page.click('#axe-revoke-do');

  await expect(page.locator('#axe-revoke-title')).toHaveText(/NÃO REVOGADO/, { timeout: 8000 });
  await expect(page.locator('#axe-revoke-status')).toContainText('database is locked');
  await expect(page.locator('#axe-revoke-status')).toHaveAttribute('data-tone', 'danger');
  // O caminho de volta existe: o botão vira TRY AGAIN e continua habilitado.
  await expect(page.locator('#axe-revoke-do')).toBeEnabled();
  await expect(page.locator('#axe-revoke-do')).toHaveText(/TRY AGAIN/);
  await expect(page.locator('#axe-revoke-body')).toContainText('continuam valendo');
});

test('um 403 de papel diz que exige admin e tira o retry de cena (Issue #586)', async ({ page }) => {
  await openAgentPanel(page);

  // A forma exata que `@role_required("admin")` devolve numa instância com auth
  // configurada — onde o RBAC morde de verdade.
  await page.route('**/api/agent/tokens/revoke', (route) =>
    route.fulfill({
      status: 403,
      contentType: 'application/json',
      body: JSON.stringify({ error: 'permission denied', required_role: 'admin', role: 'member' }),
    }),
  );

  await page.click('#axe-revoke-open');
  await page.click('#axe-revoke-do');

  await expect(page.locator('#axe-revoke-title')).toHaveText(/REVOGAÇÃO EXIGE ADMIN/, { timeout: 8000 });
  await expect(page.locator('#axe-revoke-body')).toContainText('administrador');
  // Nada foi revogado: a credencial na tela continua válida e fica onde está.
  await expect(page.locator('#axe-revoke-body')).toContainText('Nada foi revogado');
  await expect(page.locator('#axe-revoke-status')).toHaveAttribute('data-tone', 'danger');
  // O ponto do achado: "TRY AGAIN" aqui seria a UI mentindo — o papel não muda
  // entre duas tentativas.
  await expect(page.locator('#axe-revoke-do')).toBeDisabled();
  await expect(page.locator('#axe-revoke-do')).toHaveText(/ENTENDI/);
  // E a saída existe: dá para fechar o diálogo.
  await expect(page.locator('#axe-revoke-cancel')).toBeEnabled();

  await page.click('#axe-revoke-cancel');
  await expect(page.locator('#axe-revoke-confirm')).toBeHidden();
  await expect(page.locator('#axe-revoke-open')).toBeVisible();
});

test('um 403 de identidade manda entrar com a conta, não falar de papel', async ({ page }) => {
  await openAgentPanel(page);

  // A forma que `_require_caller_identity_on_cloud` devolve na nuvem sem
  // `API_KEY` — a que roda na instância pública de verdade.
  await page.route('**/api/agent/tokens/revoke', (route) =>
    route.fulfill({
      status: 403,
      contentType: 'application/json',
      body: JSON.stringify({ code: 'AGENT_TOKEN_NEEDS_IDENTITY', error: 'authentication required to manage agent tokens' }),
    }),
  );

  await page.click('#axe-revoke-open');
  await page.click('#axe-revoke-do');

  await expect(page.locator('#axe-revoke-title')).toHaveText(/REVOGAÇÃO EXIGE IDENTIDADE/, { timeout: 8000 });
  await expect(page.locator('#axe-revoke-body')).toContainText('Entre com a conta');
  await expect(page.locator('#axe-revoke-do')).toBeDisabled();
  // Falar de "papel" aqui seria diagnosticar errado: o problema é não ter
  // identidade nenhuma, não estar num papel baixo.
  await expect(page.locator('#axe-revoke-body')).not.toContainText('papel');
});

test('a barra de espera existe, mas o estado nunca depende só de movimento', async ({ page }) => {
  await openAgentPanel(page);

  await page.click('#axe-revoke-open');
  await expect(page.locator('#axe-revoke')).toHaveAttribute('data-phase', 'confirm');

  // `role=status` + aria-live: quem não vê a animação lê o mesmo recado.
  const status = page.locator('#axe-revoke-status');
  await expect(status).toHaveAttribute('role', 'status');
  await expect(status).toHaveAttribute('aria-live', 'polite');

  await page.click('#axe-revoke-do');
  await expect(page.locator('#axe-revoke-bar')).toBeAttached();

  // Com movimento reduzido a barra não varre — e a informação continua no texto.
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const animated = await page.locator('#axe-revoke-bar').evaluate(
    (el) => getComputedStyle(el).animationName,
  );
  expect(animated === 'none' || animated === '').toBe(true);
});

test('sem overflow horizontal no mobile com a confirmação aberta (768px)', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 900 });
  await openAgentPanel(page);
  await page.click('#axe-revoke-open');
  await expect(page.locator('#axe-revoke-confirm')).toBeVisible();

  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth - doc.clientWidth;
  });
  expect(overflow).toBeLessThanOrEqual(1);
});
