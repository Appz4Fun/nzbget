// Run only against an isolated NZBGet fixture. Requests to saveconfig are intercepted.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const base = process.argv[2];
  assert(base && /^http:\/\/(127\.0\.0\.1|localhost):/.test(base), 'Use a loopback fixture');
  const browser = await chromium.launch({ channel: 'chrome' });
  try {
    for (const theme of ['light', 'dark']) for (const width of [1280, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 844 } });
      await context.addInitScript(t => localStorage.setItem('Theme', t), theme);
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(base);
      await page.waitForSelector('#MainTabContent', { state: 'visible' });
      await page.locator('#ConfigTabLink').click();
      await page.locator('#ConfigNav a[href="#NEWS-SERVERS"]').press('Enter');
      assert.equal(await page.locator('.NEWS-SERVERS .config-list-edit:visible').count(), 1, 'Servers start as editable list rows');
      assert.equal(await page.locator('#S_Server1_Host').isVisible(), false, 'Server fields initially collapsed');
      await page.locator('.NEWS-SERVERS .config-list-edit').first().press('Space');
      assert.equal(await page.locator('#S_Server1_Host').isVisible(), true);
      await page.locator('#S_Server1_Name').fill('Primary <news>');
      await page.locator('.NEWS-SERVERS .config-list-edit').first().click();
      assert.match(await page.locator('.NEWS-SERVERS .config-list-name').first().innerText(), /Primary <news>/);
      assert.equal(await page.locator('#S_Server1_Host').isVisible(), false);
      // Add, move and delete must preserve flat option IDs and all unsaved values.
      await page.locator('.config-add.NEWS-SERVERS').click();
      await page.locator('#S_Server2_Name').fill('Backup');
      await page.locator('#S_Server2_Host').fill('backup.example.invalid');
      await page.locator('.NEWS-SERVERS.multiid2 .config-button').filter({ hasText: /^Up$/ }).click();
      await page.waitForTimeout(400);
      assert.equal(await page.locator('#S_Server1_Name').inputValue(), 'Backup');
      assert.equal(await page.locator('#S_Server2_Name').inputValue(), 'Primary <news>');
      assert.match(await page.locator('.config-list-row.NEWS-SERVERS.multiid1 .config-list-name').innerText(), /Backup/);
      assert.equal(await page.locator('.config-list-row.NEWS-SERVERS.multiid1 .config-list-edit').getAttribute('data-multiid'), '1');
      await page.locator('.NEWS-SERVERS.multiid1 .config-delete').click();
      await page.locator('#ConfirmDialog_OK').click();
      await page.waitForTimeout(500);
      assert.equal(await page.locator('#S_Server1_Name').inputValue(), 'Primary <news>');
      // Search must expose matching fields even when their server editor is closed.
      await page.locator('#ConfigTable_filter').fill('Server1.Host');
      await page.waitForTimeout(650);
      assert.equal(await page.locator('#S_Server1_Host').isVisible(), true);
      await page.locator('#label\\:S_Server1_Host').click();
      assert.equal(await page.locator('#S_Server1_Host').isVisible(), true, 'Search result opens server editor');
      // Help is collapsed per row, but can be expanded independently with a keyboard.
      await page.locator('#ConfigNav a[href="#WEB-INTERFACE"]').press('Enter');
      const row = page.locator('#S_ActivityAnimation').locator('xpath=ancestor::div[contains(@class,"control-group")]');
      assert.equal(await row.locator('.help-block').isVisible(), false, 'Help initially compact');
      const height = await row.evaluate(e => e.getBoundingClientRect().height);
      assert(height <= 105, 'Label-above-control tile has bounded height');
      await row.locator('.config-help-toggle').press('Space');
      assert.equal(await row.locator('.help-block').isVisible(), true);
      assert.equal(await row.locator('.config-help-toggle').getAttribute('aria-expanded'), 'true');
      await row.locator('.config-help-toggle').click();
      assert.equal(await row.locator('.help-block').isVisible(), false);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      let saved;
      await page.route('**/jsonrpc*', async route => {
        const request = route.request().postDataJSON();
        if (request && request.method === 'saveconfig') {
          saved = request.params[0];
          await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ result: true, id: request.id }) });
        } else await route.continue();
      });
      await page.locator('#Config_Save:visible').click();
      await page.waitForTimeout(400);
      assert(saved && saved.some(o => o.Name === 'Server1.Name' && o.Value === 'Primary <news>'), 'Collapsed server edits remain in save payload');
      assert.deepEqual(errors, []);
      await context.close();
      console.log(`${theme}/${width}: PASS`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
