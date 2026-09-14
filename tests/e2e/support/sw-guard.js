/**
 * Service-worker guard for E2E specs that mock `/api/*`.
 * ======================================================
 *
 * The dashboard's boot registers `/sw.js` (see `static/src/40-app-logic.js`).
 * A controlling service worker breaks every fixture that fakes a same-origin
 * GET under `/api/*`, for two independent reasons:
 *
 *   1. `page.route` does NOT intercept requests originated by a service worker.
 *      Once the SW controls the page, the app's `fetch('/api/…')` runs inside the
 *      SW's `fetch` handler — which hits the REAL server (network-first, see
 *      `static/sw.js`) and silently discards the fixture. The panel then falls
 *      back to live data instead of the mocked payload.
 *   2. `boot()` listens for `controllerchange` and calls
 *      `window.location.reload()`. A reload mid-test resets in-page state
 *      (sliders, scroll, captured globals) and makes assertions race.
 *
 * Denying registration removes both hazards: the page ends up with no controlling
 * SW, so `page.route` (or an in-page `fetch` patch) is the only source of data.
 * Specs that already use Playwright's native `test.use({ serviceWorkers: 'block' })`
 * are covered by that option and do not need this helper.
 *
 * Root cause recorded in RFC #478 (Issue #548) — the Block Hunt what-if spec was
 * failing because of the SW, not because of the `hasData` guard.
 */

/**
 * Deny service-worker registration on `page`.
 *
 * Must be called BEFORE the first navigation (`page.goto`), e.g. in a
 * `test.beforeEach` or at the start of an `addInitScript`-based fixture helper.
 *
 * @param {import('@playwright/test').Page} page Playwright page.
 * @returns {Promise<void>}
 */
export async function denyServiceWorker(page) {
  await page.addInitScript(() => {
    try {
      if (navigator.serviceWorker) {
        navigator.serviceWorker.register = () =>
          Promise.reject(new Error('sw disabled in e2e'));
      }
    } catch (e) {
      /* environment without serviceWorker — proceed without it */
    }
  });
}
