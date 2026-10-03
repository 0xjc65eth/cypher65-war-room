import { expect } from '@playwright/test';

/** Open the native More disclosure before reaching secondary header actions. */
export async function revealToolbar(page) {
  const menu = page.locator('#console-tools');
  if (!(await menu.evaluate(el => el.open))) await menu.locator('summary').click();
  await expect(menu).toHaveAttribute('open', '');
}
export async function clickToolbarAction(page, selector) {
  await revealToolbar(page);
  await page.locator(selector).click();
}
