/**
 * CYPHER65 War Room — Playwright E2E Test Configuration
 * =====================================================
 * Run:  npx playwright test
 * CI:   bash run-e2e.sh
 *
 * Tests are located in tests/e2e/*.spec.js
 */
import { defineConfig } from '@playwright/test';
import { isCiEnabled } from './tests/e2e/support/ci-policy.js';

// Environment variables are strings: Boolean('false') is true. Parse CI
// explicitly so `CI=false bash run-e2e.sh` really runs without retries.
const isCI = isCiEnabled();

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60000,
  expect: { timeout: 10000 },
  fullyParallel: false,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: 1,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'e2e-report' }],
  ],

  use: {
    baseURL: process.env.BASE_URL || 'http://127.0.0.1:8765',
    headless: true,
    viewport: { width: 1440, height: 900 },
    actionTimeout: 10000,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
    {
      name: 'mobile-chrome',
      use: {
        browserName: 'chromium',
        viewport: { width: 375, height: 812 },
      },
    },
  ],
});
