'use strict';

/**
 * Prove snapshot-failure cleanup in a fresh context, without SW interception.
 *
 * The normal boot audit still exercises service-worker-enabled browsing. This
 * separate context deliberately blocks service workers so Playwright owns the
 * failure boundary. A missing interception or incomplete probe is never green.
 *
 * @param {import('@playwright/test').Browser} browser Browser owned by the caller.
 * @param {string} baseUrl Dashboard URL of the local/test application.
 * @param {{width: number, height: number}} viewport Audit viewport.
 * @returns {Promise<{intercepted: number, leftovers: number, error: string|null}>}
 * @example
 * const result = await auditFailedSnapshot(browser, 'http://127.0.0.1:8765',
 *   {width: 375, height: 812});
 * if (snapshotFailureProblem(result)) throw new Error('Unproven cleanup');
 */
async function auditFailedSnapshot(browser, baseUrl, viewport) {
  const result = { intercepted: 0, leftovers: -1, error: null };
  let context;
  try {
    context = await browser.newContext({ viewport, serviceWorkers: 'block' });
    const page = await context.newPage();
    const target = new URL('/api/snapshot', baseUrl).href;
    const isSnapshot = (url) => new URL(url).origin === new URL(target).origin &&
      new URL(url).pathname === '/api/snapshot';
    await page.route(isSnapshot, async (route) => {
      await route.fulfill({ status: 500, contentType: 'application/json', body: '{}' });
      result.intercepted += 1;
    });
    // Register before navigation: the first request can complete during boot.
    const failedResponse = page.waitForResponse(
      (response) => isSnapshot(response.url()) && response.status() === 500,
      { timeout: 10000 }
    );
    await Promise.all([
      failedResponse,
      page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 20000 }),
    ]);
    // Keep the original bounded catch/render settling interval.
    await page.waitForTimeout(3000);
    result.leftovers = await page.evaluate(() =>
      document.querySelectorAll('.skel-overlay').length
    );
  } catch (error) {
    result.error = String(error.message || error).split('\n')[0];
  } finally {
    if (context) {
      try { await context.close(); }
      catch (error) { result.error = result.error || String(error.message || error).split('\n')[0]; }
    }
  }
  return result;
}

/**
 * Return a merge-blocking reason for an unproven or broken failure path.
 * @param {{intercepted: number, leftovers: number, error: string|null}} result Probe.
 * @returns {string|null} Null only when a 500 was injected and cleanup completed.
 * @example
 * snapshotFailureProblem({intercepted: 0, leftovers: 0, error: null}); // not green
 */
function snapshotFailureProblem(result) {
  if (result.error) return `snapshot HTTP 500 probe failed: ${result.error}`;
  if (!(result.intercepted > 0)) return 'snapshot HTTP 500 was not intercepted; failure-path cleanup is unproven';
  if (!Number.isInteger(result.leftovers) || result.leftovers < 0) return 'snapshot HTTP 500 cleanup measurement is incomplete';
  if (result.leftovers > 0) return `${result.leftovers} skeleton(s) remain after snapshot HTTP 500`;
  return null;
}

module.exports = { auditFailedSnapshot, snapshotFailureProblem };
