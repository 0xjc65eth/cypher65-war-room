/**
 * CYPHER65 War Room — E2E: FLEET PAUSE/RESUME VIA LOCAL AGENT (round-trip)
 * ========================================================================
 * Verifica o fluxo REAL de um comando Pause/Resume num device agent-managed
 * AxeOS (Issue #16 — o harness de browser antes só provava restart):
 *
 *   UI (botão ⎔ Pause / ▶ Resume no card do FLEET COMMAND CENTER)
 *     → POST /api/axe-fleet/devices/<id>/pause|resume  (enfileira no agente)
 *     → toast de sucesso "'pause' enviado para o agente local executar"
 *     → AGENTE LOCAL puxa o comando e EXECUTA no miner (log "executing pause")
 *
 * A prova de execução REAL vem do log do agente: ele loga
 * "executing pause → <device_id> (<ip>)" imediatamente antes de abrir o
 * socket/HTTP no miner da LAN. O harness (scripts/e2e_agent_local.py) é quem
 * prova, com contadores no mock, que o miningPause/miningResume chegou de
 * verdade ao device — este spec prova a ponta UI → agente.
 *
 * Por que este spec não usa o run-e2e.sh: igual ao restart-agent.spec.js, o
 * fluxo do comando só existe com o AGENTE real rodando. Este spec exige o
 * harness scripts/e2e_browser_session.py (servidor + 2 miners mock + agente
 * + state file com URL/sessão/log do agente). Sem harness, o teste dá SKIP
 * (não quebra o CI).
 *
 * Pré-requisitos / como rodar:
 *   1. python scripts/e2e_browser_session.py      # fica vivo; state em /tmp
 *   2. npx playwright test tests/e2e/pause-resume-agent.spec.js
 *
 * Para encerrar o harness:  touch /tmp/cypher65_browser_session.stop
 */

import { test, expect } from '@playwright/test';
import fs from 'fs';

// State file escrito pelo harness; override via env para CI/harness custom.
const STATE_FILE =
  process.env.CYPHER65_BROWSER_SESSION || '/tmp/cypher65_browser_session.json';

// ══════════════════════════════════════════════════════════════════════
//  Helpers (mesmas convenções de restart-agent.spec.js / dashboard.spec.js)
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
 * Count how many times the AGENT has executed a given command, by reading its
 * log file (path comes from the harness state file). The agent logs
 * "executing <command> → <device_id> (<ip>)" right before running the command
 * on the mock miner — a REAL execution proof, not just a queued row.
 */
function countAgentExecutions(agentLogPath, command) {
  try {
    const text = fs.readFileSync(agentLogPath, 'utf8');
    return (text.match(new RegExp(`executing ${command}`, 'g')) || []).length;
  } catch {
    return 0; // log ainda não existe (harness bootando)
  }
}

/** Poll the agent log until executions >= target (proves the round-trip). */
async function waitForAgentExecutions(agentLogPath, command, target, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (countAgentExecutions(agentLogPath, command) >= target) return;
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error(
    `agent nunca executou '${command}' (esperava ≥${target} execução(ões) em ${agentLogPath})`
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

test.describe('FLEET COMMAND CENTER — Pause/Resume via agent', () => {

  test('Pause → toast → agente executa de verdade → Resume → agente executa', async ({ page }) => {
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

    // ── O device AxeOS (Gamma 900) é o único com pause/resume — o cgminer
    //    honestamente não anuncia essas capabilities. O filtro `has` pega o
    //    card que tem o botão de pause (mesmo padrão do restart spec). ──
    const card = page.locator('#lm-workers-grid .fcc-card', {
      has: page.locator('.axe-cmd-btn--pause'),
    }).first();
    await expect(card).toBeVisible({ timeout: 30000 });
    const pauseBtn = card.locator('.axe-cmd-btn--pause');
    const resumeBtn = card.locator('.axe-cmd-btn--resume');
    await expect(pauseBtn).toBeVisible({ timeout: 15000 });
    await expect(resumeBtn).toBeVisible({ timeout: 5000 });

    // ── Baseline de execuções no agente (prova de round-trip) ──
    const beforePause = countAgentExecutions(agentLogPath, 'pause');
    const beforeResume = countAgentExecutions(agentLogPath, 'resume');

    // ── Pause: aceita o confirm do navegador ──
    page.once('dialog', d => d.accept());
    await pauseBtn.click();

    // ── Toast de sucesso com a mensagem do servidor (some após ~3.3s) ──
    //    Filtra pelo comando: o toast do pause e o do resume podem coexistir
    //    no DOM (o do pause ainda está saindo) — sem o filtro o locator é
    //    ambíguo (strict-mode violation).
    const toastPause = page.getByText(
      "'pause' enviado para o agente local executar");
    await expect(toastPause).toBeVisible({ timeout: 8000 });
    await expect(toastPause).toContainText('pause');

    // ── O AGENTE REAL puxou o comando e executou no miner (anti-teatro) ──
    await waitForAgentExecutions(agentLogPath, 'pause', beforePause + 1, 20000);

    // ── Resume: ação segura, sem confirm — dispara direto ──
    await resumeBtn.click();

    const toastResume = page.getByText(
      "'resume' enviado para o agente local executar");
    await expect(toastResume).toBeVisible({ timeout: 8000 });
    await expect(toastResume).toContainText('resume');

    await waitForAgentExecutions(agentLogPath, 'resume', beforeResume + 1, 20000);

    // ── Sem erros de console no painel ──
    const critical = capture.getCritical();
    expect(critical.length).toBe(0,
      `Critical console errors: ${JSON.stringify(critical)}`);
  });
});
