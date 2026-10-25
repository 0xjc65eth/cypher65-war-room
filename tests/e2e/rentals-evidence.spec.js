// @ts-check
// Issue #599: tenant-authenticated, operator-declared destination-pool evidence.
// API fixtures exercise source provenance, explicit rules, missing != zero,
// stale verdicts, retained CSV, safe text and cross-rental request ordering.
import { test, expect } from '@playwright/test';

test.use({ serviceWorkers: 'block', contextOptions: { reducedMotion: 'reduce' } });

const NOW = 1800000000;
const SOURCE = {
  id: 1, address: 'bc1qoperatorwallet', worker_key: 'id', worker_value: 'rental-worker',
  label: 'worker exclusivo', source: 'parasite_pool_worker', last_seen: NOW,
};
const BINDING = {
  provider: 'mrr', rental_id: '101', source_id: 1, contract_th: 100,
  threshold_pct: 90, duration_s: 60, max_gap_s: 30, revision: 1, created_at: NOW - 60,
};
const POINT = {
  observed_at: NOW, source: 'parasite_pool_worker',
  source_url: 'https://parasite.space/api/user/bc1qoperatorwallet',
  address: SOURCE.address, worker_key: SOURCE.worker_key, worker_value: SOURCE.worker_value,
  collection_started_at: NOW - 1, collection_completed_at: NOW,
  upstream_measured_at: null, averaging_window_s: null,
  hashrate_th: 0, quality: 'observed', delivery_pct: 0,
  provider: 'mrr', rental_id: '101', revision: 1, config: BINDING,
};

function evidence(status = 'under_delivery') {
  const available = ['under_delivery', 'healthy', 'watching', 'insufficient'].includes(status);
  const healthy = status === 'healthy';
  return {
    success: true, binding: BINDING, sources: [SOURCE],
    evaluation: { status, last_observed_at: available ? NOW : null, window_start: healthy || !available ? null : NOW - 60,
      window_end: healthy || !available ? null : NOW, samples: healthy || !available ? 0 : 3,
      observed_th: available ? (healthy ? 100 : 0) : null, delivery_pct: available ? (healthy ? 100 : 0) : null,
      alert: status === 'under_delivery' ? { threshold_pct: 90, duration_s: 60, max_gap_s: 30, observed_at: NOW } : null },
    coverage: available ? { status: 'AVAILABLE', observation_count: 4, observed_count: 3, missing_count: 1, observed_pct: 75,
      window_start: NOW - 90, window_end: NOW } : { status: 'NO DATA', observation_count: 0, observed_count: 0, missing_count: 0,
      observed_pct: null, window_start: null, window_end: null },
    points: available ? [{ ...POINT, hashrate_th: healthy ? 100 : 0, delivery_pct: healthy ? 100 : 0 }] : [], limitations: [],
  };
}

/** Route the existing provider UI; evidence remains a separate API contract. */
async function mockProvider(page) {
  const rental = id => ({
    id, ended: false, hashrate_average_th: 100, hashrate_advertised_th: 100,
    hashrate_percent: 100, price_paid_btc: 0.0001, length_hours: 1,
    rig: { id: 'rig-' + id, name: 'Rig ' + id, status: 'running' },
  });
  await page.route('**/api/rentals', route => route.fulfill({ json: {
    success: true, rentals_payload_version: 2, updated_at: Date.now() / 1000,
    mrr: { needs_auth: false, active: [rental('101'), rental('102')], history: [], owner: [],
      total_active: 2, total_history: 0, total_owner: 0, error: null },
    braiins: { needs_auth: false, contracts: [], error: null },
  } }));
  await page.route('**/api/rentals/detail*', route => route.fulfill({ json: {
    success: true, provider: 'mrr', detail: {
      id: new URL(route.request().url()).searchParams.get('id'),
      hashrate: { advertised: { hash: 100, type: 'th', nice: '100 TH/s' },
        average: { hash: 100, type: 'th', percent: 100 } },
      rig: {}, price: { paid: 0.0001 }, length: 1,
    }, graph: {}, log: {},
  } }));
}

async function openRental(page, id = '101') {
  await page.goto('/');
  await page.waitForSelector('#sidebar', { timeout: 25000 });
  const toggle = page.locator('#sidebar-mobile-toggle');
  if (await toggle.isVisible() && !(await page.locator('#sidebar').evaluate(el => el.classList.contains('open')))) {
    await toggle.click();
  }
  await page.locator('.sidebar__link[data-module="rentals"]').evaluate(el => el.click());
  await page.locator('#rentals-list .rentals-item[data-rental-id="' + id + '"]').click();
  await expect(page.locator('#rentals-evidence')).toBeVisible();
  await expect(page.locator('#rentals-evidence-summary')).toHaveAttribute('aria-busy', 'false');
}

test('regra exige worker exclusivo e valores explícitos sem limites automáticos', async ({ page }) => {
  await mockProvider(page);
  let saved = null;
  await page.route('**/api/rentals/101/evidence?provider=mrr', route => {
    if (route.request().method() === 'POST') {
      saved = route.request().postDataJSON();
      return route.fulfill({ json: evidence('missing') });
    }
    return route.fulfill({ json: saved ? evidence('missing') : {
      success: true, binding: null, sources: [SOURCE], evaluation: { status: 'unconfigured' }, points: [],
    } });
  });
  await openRental(page);
  await expect(page.locator('#rentals-evidence-contract')).toHaveValue('');
  await expect(page.locator('#rentals-evidence-threshold')).toHaveValue('');
  await expect(page.locator('#rentals-evidence-duration')).toHaveValue('');
  await expect(page.locator('#rentals-evidence-gap')).toHaveValue('');
  await page.selectOption('#rentals-evidence-source', '1');
  await page.fill('#rentals-evidence-contract', '100');
  await page.fill('#rentals-evidence-threshold', '90');
  await page.fill('#rentals-evidence-duration', '60');
  await page.fill('#rentals-evidence-gap', '30');
  await page.click('#rentals-evidence-save');
  expect(saved).toBeNull();
  await page.check('#rentals-evidence-exclusive');
  await page.click('#rentals-evidence-save');
  await expect(page.locator('#rentals-evidence-summary')).toContainText('Sem observações');
  expect(saved).toEqual({ source_id: 1, contract_th: 100, threshold_pct: 90,
    duration_s: 60, max_gap_s: 30, exclusive_worker: true });
});

test('lacuna maior que duração bloqueia envio e permite corrigir a regra', async ({ page }) => {
  await mockProvider(page);
  let saves = 0;
  await page.route('**/api/rentals/101/evidence?provider=mrr', route => {
    if (route.request().method() === 'POST') saves++;
    return route.fulfill({ json: evidence() });
  });
  await openRental(page);
  await page.fill('#rentals-evidence-gap', '90');
  await page.click('#rentals-evidence-save');
  expect(saves).toBe(0);
  expect(await page.locator('#rentals-evidence-gap').evaluate(el => /** @type {HTMLInputElement} */ (el).validationMessage)).toContain('lacuna');
  await page.fill('#rentals-evidence-gap', '30');
  await page.click('#rentals-evidence-save');
  await expect.poll(() => saves).toBe(1);
});

test('observação zero mantém fonte, UTC e intervalo de coleta sem inventar média', async ({ page }) => {
  await mockProvider(page);
  await page.route('**/api/rentals/101/evidence?provider=mrr', route => route.fulfill({ json: evidence() }));
  await openRental(page);
  const summary = page.locator('#rentals-evidence-summary');
  await expect(summary).toContainText('Leituras abaixo do limite');
  const observed = summary.locator('.rentals-evidence__metric').filter({ has: page.locator('span', { hasText: /^Hashrate observado$/ }) });
  await expect(observed.locator('strong')).toHaveText('0 TH/s');
  await expect(summary).toContainText('2027-01-15 08:00:00 UTC');
  await expect(summary).toContainText('id: rental-worker');
  await expect(summary).toContainText('Cobertura das amostras retidas75% · 3/4 válidas');
  await expect(summary).toContainText('Janela média do poolNão informada');
  await expect(page.locator('#rentals-evidence-limitations')).toContainText('amostragem não comprova entrega contínua');
  await expect(page.locator('#rentals-evidence-observations')).toContainText('Coleta:');
  expect(await page.locator('#rentals-evidence').evaluate(el => getComputedStyle(el).animationName)).toBe('none');
});

test('stale e valor ausente não reutilizam o alerta de subentrega', async ({ page }) => {
  await mockProvider(page);
  let stale = false;
  await page.route('**/api/rentals/101/evidence?provider=mrr', route => {
    const payload = evidence(stale ? 'stale' : 'under_delivery');
    if (stale) {
      payload.evaluation.observed_th = null;
      payload.evaluation.delivery_pct = null;
      payload.points = [{ ...POINT, quality: 'missing', hashrate_th: null, delivery_pct: null }];
    }
    return route.fulfill({ json: payload });
  });
  await openRental(page);
  await expect(page.locator('#rentals-evidence-summary')).toContainText('Leituras abaixo do limite');
  stale = true;
  await page.click('#rentals-evidence-refresh');
  await expect(page.locator('#rentals-evidence-summary')).toContainText('Dados antigos');
  await expect(page.locator('#rentals-evidence-summary')).not.toContainText('Leituras abaixo do limite');
  const observed = page.locator('#rentals-evidence-summary .rentals-evidence__metric').filter({ has: page.locator('span', { hasText: /^Hashrate observado$/ }) });
  await expect(observed.locator('strong')).toHaveText('—');
  await expect(page.locator('#rentals-evidence-observations')).toContainText('Valor ausente');
});

test('desativação preserva export CSV das revisões retidas', async ({ page }) => {
  await mockProvider(page);
  let disabled = false;
  await page.route('**/api/rentals/101/evidence?provider=mrr', route => {
    if (route.request().method() === 'DELETE') disabled = true;
    return route.fulfill({ json: disabled ? {
      success: true, binding: null, sources: [SOURCE], evaluation: { status: 'unconfigured' }, points: [],
    } : evidence() });
  });
  await page.route('**/api/rentals/101/evidence/export?provider=mrr', route => route.fulfill({
    contentType: 'text/csv', body: 'source,observed_at,hashrate_th\nparasite_pool_worker,1800000000,0\n',
  }));
  await openRental(page);
  await page.click('#rentals-evidence-remove');
  await expect(page.locator('#rentals-evidence-summary')).toContainText('Sem vínculo configurado');
  await expect(page.locator('#rentals-evidence-summary')).toContainText('Contrato declaradoNão configurado');
  await expect(page.locator('#rentals-evidence-summary')).toContainText('Cobertura das amostras retidasSem observações');
  await expect(page.locator('#rentals-evidence-remove')).toBeHidden();
  const downloadPromise = page.waitForEvent('download');
  await page.click('#rentals-evidence-export');
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('rental_evidence_101.csv');
});

test('fonte externa é texto seguro e recusa do servidor é visível', async ({ page }) => {
  await mockProvider(page);
  const maliciousSource = { ...SOURCE, worker_value: '<img src=x onerror="window.__evidenceXss=1">' };
  await page.route('**/api/rentals/101/evidence?provider=mrr', route => {
    if (route.request().method() === 'POST') return route.fulfill({ status: 400,
      json: { success: false, error: 'Este worker já está vinculado a outro aluguel.' } });
    return route.fulfill({ json: { ...evidence(), sources: [maliciousSource] } });
  });
  await openRental(page);
  await expect(page.locator('#rentals-evidence-source')).toContainText('<img');
  expect(await page.evaluate(() => window['__evidenceXss'])).toBeUndefined();
  await page.click('#rentals-evidence-save');
  await expect(page.locator('#rentals-evidence-message')).toContainText('já está vinculado');
  await expect(page.locator('#rentals-evidence-summary')).not.toContainText('Leituras abaixo do limite');
});

test('resposta atrasada do aluguel anterior não sobrescreve evidência atual', async ({ page }) => {
  await mockProvider(page);
  let release;
  const waitForRelease = new Promise(resolve => { release = resolve; });
  let started = false;
  await page.route('**/api/rentals/101/evidence?provider=mrr', async route => {
    started = true;
    await waitForRelease;
    await route.fulfill({ json: evidence('under_delivery') });
  });
  await page.route('**/api/rentals/102/evidence?provider=mrr', route => route.fulfill({ json: {
    ...evidence('healthy'), binding: { ...BINDING, rental_id: '102' },
  } }));
  await page.goto('/');
  await page.waitForSelector('#sidebar', { timeout: 25000 });
  const toggle = page.locator('#sidebar-mobile-toggle');
  if (await toggle.isVisible()) await toggle.click();
  await page.locator('.sidebar__link[data-module="rentals"]').evaluate(el => el.click());
  await page.locator('#rentals-list .rentals-item[data-rental-id="101"]').click();
  await expect.poll(() => started).toBe(true);
  await page.locator('#rentals-list .rentals-item[data-rental-id="102"]').click();
  await expect(page.locator('#rentals-evidence-summary')).toContainText('Leituras dentro do limite');
  const delayedResponse = page.waitForResponse(response => response.url().includes('/101/evidence?'));
  release();
  await (await delayedResponse).finished();
  // Let the completed response's promise and rendering tasks settle.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.locator('#rentals-detail-title')).toContainText('#102');
  await expect(page.locator('#rentals-evidence-summary')).not.toContainText('Leituras abaixo do limite');
});
