// ESM-compatible — run via: npx playwright test tests/e2e/terminal-test.js
import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';

test.describe('Live Terminal', () => {

  test('terminal tab contains input and body elements', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForTimeout(3000);

    // Click the Terminal sidebar link
    const terminalSidebarBtn = page.locator('.sidebar__link[data-section="terminal"]');
    await expect(terminalSidebarBtn).toBeVisible({ timeout: 5000 });
    await terminalSidebarBtn.click();
    await page.waitForTimeout(2000);

    // Check that the tab pane is now visible
    const tabPane = page.locator('#tab-terminal');
    await expect(tabPane).toBeVisible({ timeout: 3000 });

    // Check terminal body exists
    const terminalBody = page.locator('#terminal-body');
    await expect(terminalBody).toBeVisible({ timeout: 3000 });

    // Check terminal input exists and is focused
    const terminalInput = page.locator('#terminal-input');
    await expect(terminalInput).toBeVisible({ timeout: 3000 });
    await expect(terminalInput).toBeFocused();

    // Check the prompt exists
    const prompt = page.locator('.terminal-prompt');
    await expect(prompt).toBeVisible({ timeout: 1000 });
    await expect(prompt).toHaveText('$');
  });

  test('help command shows available commands list', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForTimeout(3000);

    // Navigate to terminal
    await page.locator('.sidebar__link[data-section="terminal"]').click();
    await page.waitForTimeout(2000);

    // Type 'help' and press Enter
    const input = page.locator('#terminal-input');
    await input.fill('help');
    await input.press('Enter');
    await page.waitForTimeout(1000);

    // Check that output appeared in terminal body
    const terminalBody = page.locator('#terminal-body');
    const bodyText = await terminalBody.textContent();
    expect(bodyText).toContain('help');
    expect(bodyText).toContain('Available commands');
  });

  test('status command shows system state', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForTimeout(8000); // Wait for polling data

    // Navigate to terminal
    await page.locator('.sidebar__link[data-section="terminal"]').click();
    await page.waitForTimeout(2000);

    // Type 'status' and press Enter
    const input = page.locator('#terminal-input');
    await input.fill('status');
    await input.press('Enter');
    await page.waitForTimeout(1000);

    // Check output
    const terminalBody = page.locator('#terminal-body');
    const bodyText = await terminalBody.textContent();
    expect(bodyText).toContain('CYPHER65');
    expect(bodyText).toContain('ONLINE');
  });

  test('unknown command shows error message', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForTimeout(3000);

    // Navigate to terminal
    await page.locator('.sidebar__link[data-section="terminal"]').click();
    await page.waitForTimeout(2000);

    // Type unknown command
    const input = page.locator('#terminal-input');
    await input.fill('foobar123');
    await input.press('Enter');
    await page.waitForTimeout(1000);

    // Check error output
    const terminalBody = page.locator('#terminal-body');
    const bodyText = await terminalBody.textContent();
    expect(bodyText).toContain('Unknown command');
    expect(bodyText).toContain('help');
  });

  test('clear command empties terminal body', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForTimeout(3000);

    // Navigate to terminal
    await page.locator('.sidebar__link[data-section="terminal"]').click();
    await page.waitForTimeout(2000);

    const input = page.locator('#terminal-input');
    const terminalBody = page.locator('#terminal-body');

    // First add some content
    await input.fill('help');
    await input.press('Enter');
    await page.waitForTimeout(500);
    let bodyText = await terminalBody.textContent();
    expect(bodyText.length).toBeGreaterThan(10);

    // Now clear
    await input.fill('clear');
    await input.press('Enter');
    await page.waitForTimeout(500);

    // Terminal body should now be empty or contain only clear confirmation
    bodyText = await terminalBody.textContent();
    expect(bodyText ? bodyText.trim().length : 0).toBeLessThan(50);
  });

  test('workers command shows worker data', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForTimeout(10000); // Wait for polling data

    // Navigate to terminal
    await page.locator('.sidebar__link[data-section="terminal"]').click();
    await page.waitForTimeout(2000);

    // Type 'workers'
    const input = page.locator('#terminal-input');
    await input.fill('workers');
    await input.press('Enter');
    await page.waitForTimeout(1000);

    // Check output
    const terminalBody = page.locator('#terminal-body');
    const bodyText = await terminalBody.textContent();
    expect(bodyText).toContain('workers');
    expect(bodyText).toContain('HR');
  });

  test('price command shows BTC price data', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForTimeout(10000);

    // Navigate to terminal
    await page.locator('.sidebar__link[data-section="terminal"]').click();
    await page.waitForTimeout(2000);

    // Type 'price'
    const input = page.locator('#terminal-input');
    await input.fill('price');
    await input.press('Enter');
    await page.waitForTimeout(1000);

    // Check output
    const terminalBody = page.locator('#terminal-body');
    const bodyText = await terminalBody.textContent();
    expect(bodyText).toContain('BTC');
  });

  test('clear button clears the terminal', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForTimeout(3000);

    // Navigate to terminal
    await page.locator('.sidebar__link[data-section="terminal"]').click();
    await page.waitForTimeout(2000);

    const input = page.locator('#terminal-input');
    const terminalBody = page.locator('#terminal-body');

    // Add content
    await input.fill('help');
    await input.press('Enter');
    await page.waitForTimeout(500);

    // Click the clear button
    await page.locator('#terminal-clear').click();
    await page.waitForTimeout(500);

    // Terminal should show "terminal cleared"
    const bodyText = await terminalBody.textContent();
    expect(bodyText).toContain('terminal cleared');
  });
});
