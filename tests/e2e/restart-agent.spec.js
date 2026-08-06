/**
 * CYPHER65 War Room — E2E: FLEET RESTART VIA LOCAL AGENT (round-trip)
 * ==================================================================
 * Verifica o fluxo REAL de um comando Restart num device agent-managed:
 *
 *   UI (botão ↻ Restart no card do FLEET COMMAND CENTER)
 *     → POST /api/axe-fleet/devices/<id>/restart  (enfileira no agente)
 *     → toast de sucesso "'restart' enviado para o agente local executar"
 *     → AGENTE LOCAL puxa o comando e EXECUTA no miner (log "executing restart")
 *
 * Por que este spec não usa o run-e2e.sh: o fluxo do comando só existe de
 * verdade com o AGENTE real rodando. O runner padrão sobe só o servidor
 * (sem mocks nem agente) — o botão responderia 404/teatro. Este spec exige
 * o harness scripts/e2e_browser_session.py, que sobe servidor + 2 miners
 * mock + agente e grava o state file com URL, sessão e caminho do log do
 * agente. Sem harness, o teste dá SKIP (não quebra o CI).
 *
 * Pré-requisitos / como rodar:
 *   1. python scripts/e2e_browser_session.py      # fica vivo; state em /tmp
 *   2. npx playwright test tests/e2e/restart-agent.spec.js
 *
 * Para encerrar o harness:  touch /tmp/cypher65_browser_session.stop
 */

import { test, expect } from '@playwright/test';
import fs from 'fs';

// State file escrito pelo harness; override via env para CI/harness custom.
const STATE_FILE =
  process.env.CYPHER65_BROWSER_SESSION || '/tmp/cypher65_browser_session.json';

// ══════════════════════════════════════════════════════════════════════
//  Helpers (mesmas convenções de dashboard.spec.js / live-mining.spec.js)
// ══════════════════════════════════════════════════════════════════════

/** Wait for the page to fully load and complete at least one poll cycle */
async function waitForDashboard(page) {
  await page.waitForSelector('#app-shell', { timeout: 15000 });
  await Promise.race([
    page.waitForFunction(() => {
      const el = document.getElementById('m-hashrate');
      return el && el.textContent && !el.textContent.includes('—');
    }, { timeout: 20000 }),
    page.waitForSelector('#status-bar', { timeout: 10000 }),
    page.waitForTimeout(8000),
  ]);
  await page.waitForTimeout(1000);
}

/** Attach console + page error listeners and return a checker object */
function setupErrorCapture(page) {
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', err => errors.push(err.message));
  return {
    getCritical() {
      return errors.filter(e =>
        !e.includes('[boot]') && !e.includes('ServiceWorker')
      );
    },
    all() { return errors; },
  };
}

/** Ensure the sidebar is open so sidebar links are clickable (mobile off-canvas) */
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

/**
 * Count how many times the AGENT has executed a restart, by reading its log
 * file (path comes from the harness state file). The agent logs
 * "executing restart → <device_id> (<ip>)" right before running the command
 * on the mock miner — a REAL execution proof, not just a queued row.
 */
function countAgentExecutions(agentLogPath) {
  try {
    const text = fs.readFileSync(agentLogPath, 'utf8');
    return (text.match(/executing restart/g) || []).length;
  } catch {
    return 0; // log ainda não existe (harness bootando)
  }
}

/** Poll the agent log until executions >= target (proves the round-trip). */
async function waitForAgentExecutions(agentLogPath, target, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (countAgentExecutions(agentLogPath) >= target) return;
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error(
    `agent nunca executou o restart (esperava ≥${target} execução(ões) em ${agentLogPath})`
  );
}

/**
 * Read + validate the harness state file. Returns null when the harness is
 * NOT usable — missing, stale (orphaned by a SIGKILL'd harness), truncated
 * or missing auth fields — so the test SKIPS instead of erroring in CI.
 */
function readHarnessState() {
  try {
    if (!fs.existsSync(STATE_FILE)) return null;
    const state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    if (!state || !state.base_url || !state.session ||
        !state.session.access_token || !state.agent_log) {
      return null;
    }
    return state;
  } catch {
    return null; // corrompido / parcial — não é harness utilizável
  }
}

// ══════════════════════════════════════════════════════════════════════
//  Tests
// ══════════════════════════════════════════════════════════════════════

test.describe('FLEET COMMAND CENTER — Restart via agent', () => {

  test('botão Restart do card → toast de sucesso → agente executa de verdade', async ({ page }) => {
    test.setTimeout(120000);

    // Skip sem o harness: quem roda o CI (run-e2e.sh, servidor só) não deve
    // quebrar — o fluxo do comando simplesmente não existe lá.
    const state = readHarnessState();
    test.skip(!state,
      `harness não está rodando/usável — suba com: ` +
      `python scripts/e2e_browser_session.py ` +
      `(state file esperado: ${STATE_FILE})`);
    const baseUrl = state.base_url;
    const agentLogPath = state.agent_log;
    const session = state.session;

    // ── State file órfão (harness morto com SIGKILL): o arquivo existe mas
    //    o servidor não responde — goto falharia e QUEBRARIA o CI. Probe
    //    rápido e skip honesto. ──
    let serverAlive = false;
    try {
      const probe = await page.request.get(baseUrl, { timeout: 4000 });
      serverAlive = probe.ok() || probe.status() >= 300; // redirects also prove aliveness
    } catch { /* unreachable */ }
    test.skip(!serverAlive,
      `harness não responde em ${baseUrl} (state file órfão?) — ` +
      `suba com: python scripts/e2e_browser_session.py`);

    const capture = setupErrorCapture(page);

    // ── Sessão do tenant: injeta exatamente o que o harness autenticou ──
    //    Espera o #app-shell existir antes do evaluate — a primeira goto
    //    cai em `/` que faz redirect para o dashboard e destruiria o
    //    contexto de execução a meio do page.evaluate (race clássico).
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await page.evaluate(s => {
      localStorage.setItem('_cypher65_auth_session', JSON.stringify(s));
    }, session);
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
    await waitForDashboard(page);

    // ── Abre o FLEET COMMAND CENTER (Live Mining) ──
    await ensureSidebarOpen(page);
    await page.locator('.sidebar__link[data-module="live"]').click();
    await page.waitForTimeout(600);

    // ── Primeiro card de worker (os 2 devices do harness são agent-managed) ──
    const card = page.locator('#lm-workers-grid .fcc-card').first();
    await expect(card).toBeVisible({ timeout: 30000 });
    const restartBtn = card.locator('.axe-cmd-btn--restart');
    await expect(restartBtn).toBeVisible({ timeout: 15000 });

    // ── Baseline de execuções no agente (prova de round-trip) ──
    const before = countAgentExecutions(agentLogPath);

    // ── Clique no Restart: aceita o confirm do navegador ──
    page.once('dialog', d => d.accept());
    await restartBtn.click();

    // ── Toast de sucesso com a mensagem do servidor (some após ~3.3s) ──
    const toast = page.locator('#toast-container div', {
      hasText: 'enviado para o agente local executar',
    });
    await expect(toast).toBeVisible({ timeout: 8000 });
    await expect(toast).toContainText('restart');

    // ── O AGENTE REAL puxou o comando e executou no miner (anti-teatro) ──
    //    O harness polla a fila a cada 2s — folga generosa para o log.
    await waitForAgentExecutions(agentLogPath, before + 1, 20000);

    // ── Sem erros de console no painel ──
    const critical = capture.getCritical();
    expect(critical.length).toBe(0,
      `Critical console errors: ${JSON.stringify(critical)}`);
  });
});
