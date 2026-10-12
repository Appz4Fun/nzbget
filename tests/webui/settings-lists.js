// Use an isolated loopback fixture; saveconfig is intercepted, never persisted.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const base = process.argv[2];
  assert(base && /^http:\/\/(127\.0\.0\.1|localhost):/.test(base), 'Use a loopback fixture');
  const browser = await chromium.launch({channel: 'chrome'});
  try {
    for (const theme of ['light', 'dark']) for (const width of [1280, 390]) {
      const context = await browser.newContext({viewport: {width, height: 844}});
      await context.addInitScript(t => localStorage.setItem('Theme', t), theme);
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(base);
      await page.waitForSelector('#MainTabContent', {state: 'visible'});
      await page.locator('#ConfigTabLink').click();
      const expected = [];
      for (const [section, prefix, field] of [['CATEGORIES', 'Category', 'Name'], ['RSS_FEEDS', 'Feed', 'Name'], ['SCHEDULER', 'Task', 'Time']]) {
        await page.locator(`#ConfigNav a[href="#${section}"]`).press('Enter');
        const initial = await page.locator(`.config-settitle.${section}`).count();
        assert.equal(await page.locator(`.config-list-row.${section}`).count(), initial, `${section} uses compact list rows`);
        assert.equal(await page.locator(`.config-list-detail.${section}:visible`).count(), 0, 'Editors initially collapsed');
        // Add opens only the new editor, even with shared multiid values across sections.
        await page.locator(`.config-add.${section}`).click();
        const id = initial + 1;
        const input = page.locator(`#S_${prefix}${id}_${field}`);
        await input.waitFor({state: 'visible'});
        const value = prefix === 'Task' ? '06:30' : `${prefix} <compact>`;
        await input.fill(value);
        const edit = page.locator(`.config-list-row.${section}.multiid${id} .config-list-edit`);
        const controls = (await edit.getAttribute('aria-controls')).split(' ');
        assert(controls.includes(`S_${prefix}${id}_${field}`));
        assert(controls.every(c => c.startsWith(`S_${prefix}${id}_`)), 'Editor controls scoped to this entry');
        await edit.press('Space');
        assert.equal(await input.isVisible(), false);
        assert.match(await page.locator(`.config-list-row.${section}.multiid${id}`).innerText(), new RegExp(value.replace(/[<>]/g, '.')));
        await edit.press('Enter');
        assert.equal(await input.isVisible(), true);
        // Sensitive feed URL / scheduler command parameters must never appear in summaries.
        if (prefix !== 'Category') {
          await page.locator(`#S_${prefix}${id}_${prefix === 'Feed' ? 'URL' : 'Param'}`).fill('secret-summary-marker');
          assert(!(await page.locator(`.config-list-row.${section}.multiid${id}`).innerText()).includes('secret-summary-marker'));
        }
        await page.locator(`.config-add.${section}`).click();
        await page.locator(`#S_${prefix}${id + 1}_${field}`).fill(prefix === 'Task' ? '07:45' : 'Second');
        await page.locator(`.${section}.multiid${id + 1} .config-button`).filter({hasText: /^Up$/}).click();
        await page.waitForTimeout(400);
        assert.equal(await page.locator(`#S_${prefix}${id + 1}_${field}`).inputValue(), value);
        await page.locator(`.${section}.multiid${id} .config-delete`).click();
        await page.locator('#ConfirmDialog_OK').click();
        await page.waitForTimeout(500);
        assert.equal(await input.inputValue(), value);
        const currentEdit = page.locator(`.config-list-row.${section}.multiid${id} .config-list-edit`);
        if (await currentEdit.getAttribute('aria-expanded') === 'true') await currentEdit.click();
        assert.equal(await input.isVisible(), false);
        await page.locator('#ConfigTable_filter').fill(`${prefix}${id}.${field}`);
        await page.waitForTimeout(650);
        assert.equal(await input.isVisible(), true, 'Search exposes closed fields');
        await page.locator(`#label\\:S_${prefix}${id}_${field}`).click();
        assert.equal(await currentEdit.getAttribute('aria-expanded'), 'true');
        await page.locator('#ConfigTable_filter').fill('');
        await page.locator('#ConfigNav .ConfigSearch').first().waitFor({state: 'hidden'});
        await currentEdit.click();
        const row = page.locator(`.config-list-row.${section}.multiid${id}`);
        assert((await row.boundingBox()).height <= (width === 390 ? 170 : 75), 'Summary stays compact');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        expected.push([`${prefix}${id}.${field}`, value]);
      }
      let saved;
      await page.route('**/jsonrpc*', async route => {
        const req = route.request().postDataJSON();
        if (req && req.method === 'saveconfig') {
          saved = req.params[0];
          await route.fulfill({contentType: 'application/json', body: JSON.stringify({result: true, id: req.id})});
        } else await route.continue();
      });
      await page.locator('#Config_Save:visible').click();
      await page.waitForTimeout(400);
      for (const [name, value] of expected) assert(saved.some(o => o.Name === name && o.Value === value), 'Closed editors retain unsaved values');
      assert.deepEqual(errors, []);
      await context.close();
      console.log(`${theme}/${width}: PASS`);
    }
  } finally {await browser.close();}
})().catch(e => {console.error(e.message); process.exitCode = 1;});
