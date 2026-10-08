import {test,expect} from '@playwright/test';
import {revealToolbar} from './support/toolbar.js';

// test-requirement: UI-001 status=partial
test('header controls and source console adapt across four breakpoints',async({page},info)=>{
  test.skip(info.project.name==='mobile-chrome','Explicit viewport sequence runs once in desktop project');
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');await expect(page.locator('#operation-console')).toBeVisible();
  for(const width of [1100,768,600,375]) {
    await page.setViewportSize({width,height:900});
    for(const id of ['refresh-now','open-settings','theme-toggle']) await expect(page.locator('button#'+id)).toBeVisible();
    for(const id of ['tbar-hr','tbar-best','tbar-status','tbar-workers','tbar-btc']) await expect(page.locator('#'+id)).toBeHidden();
    await expect(page.locator('.topbar__brand')).toBeVisible();
    await revealToolbar(page);await expect(page.locator('button#open-exports')).toBeVisible();
    await page.locator('#console-tools > summary').click();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  }
  await page.locator('#open-settings').click();await expect(page.locator('#settings-modal')).toBeVisible();
  await page.keyboard.press('Escape');await expect(page.locator('#settings-modal')).toBeHidden();
  await page.locator('#theme-toggle').click();await expect(page.locator('html')).toHaveAttribute('data-theme','light');
  await page.locator('#theme-toggle').click();await expect(page.locator('html')).not.toHaveAttribute('data-theme','light');
  const sidebar=page.locator('#sidebar'),toggle=page.locator('#sidebar-mobile-toggle');
  await toggle.click();await expect(sidebar).toHaveClass(/open/);await toggle.click();await expect(sidebar).not.toHaveClass(/open/);
  expect(errors).toEqual([]);
});
