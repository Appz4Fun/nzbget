// Use real UI callers on an isolated daemon; every tested mutation is intercepted.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const { fixtureURL, installFixture } = require('./workspace-fixture');

(async () => {
  const base = fixtureURL(process.argv[2]);
  const browser = await chromium.launch({ channel: 'chrome' });
  const failures = [];
  try {
    for (const theme of ['light', 'dark']) for (const width of [1920, 1280, 768, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      await context.addInitScript(t => localStorage.setItem('Theme', t), theme);
      const page = await context.newPage();
      const writes = [], errors = [];
      await installFixture(page, writes);
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(base.href);
      await page.locator('#MainTabContent').waitFor({ state: 'visible' });
      async function check(label, action) {
        try { await action(); } catch (error) { failures.push(`${theme}/${width}/${label}: ${error.message}`); }
      }
      for (const tab of ['Downloads', 'History', 'Statistics', 'Messages']) {
        await page.locator(`#${tab}TabLink`).click();
        await page.waitForFunction(id => getComputedStyle(document.getElementById(id)).opacity === '1', `${tab}Tab`);
        if (tab === 'Statistics') await page.locator('.statistics__server-details:visible').first().waitFor();
        await check(tab + ' heading', async () => {
          assert.equal(await page.locator(`#${tab}Tab`).getByRole('heading', { name: tab, exact: true }).count(), 1,
            'Each screen has its own accessible heading, including icon-only phone navigation');
        });
        await check(tab + ' panel', async () => {
          const panel = page.locator(`#${tab}Tab .workspace-panel:visible`).first();
          assert.equal(await panel.count(), 1);
          const box = await panel.boundingBox();
          assert(box.x >= 0 && box.x + box.width <= width + 1, 'Panel stays inside viewport');
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
          if (tab === 'Statistics') {
            const details = await panel.locator('.statistics__server-details').boundingBox();
            const chart = await panel.locator('.statistics:visible').boundingBox();
            assert(details.x + details.width <= box.x + box.width - 10);
            assert(chart.x >= details.x + details.width || chart.y >= details.y + details.height,
              'Provider details and chart do not overlap');
          } else {
            const wrap = page.locator(`#${tab}Tab .workspace-table-wrap`);
            const table = await wrap.boundingBox();
            assert(table.x >= box.x + 10 && table.x + table.width <= box.x + box.width - 10,
              'The table viewport retains breathing room inside the Settings-style surface');
            await wrap.evaluate(e => { e.scrollLeft = e.scrollWidth; });
            const last = await (width >= 768 ? page.locator(`#${tab}Table thead tr`).first().locator('th').last() : page.locator(`#${tab}Table tbody tr:visible`).last().locator('td:visible').last()).boundingBox();
            assert(last.x >= table.x - 1 && last.x + last.width <= table.x + table.width + 1,
              'The final column remains reachable in the bounded scroll area');
            await wrap.evaluate(e => { e.scrollLeft = 0; });
            const toolbar = page.locator(`#${tab}Tab .section-toolbar`).first();
            const controls = await toolbar.locator('button:visible, select:visible, .pagination a:visible').evaluateAll(es => es.map(e => {
              const r = e.getBoundingClientRect(); return { x: r.x, right: r.right, width: r.width };
            }));
            for (const control of controls) assert(control.x >= box.x && control.right <= box.x + box.width + 1);
          }
        });
        if (process.env.NZBGET_UI_CAPTURE_DIR && [1280, 390].includes(width)) {
          await page.evaluate(() => document.fonts.ready);
          await page.screenshot({ path: path.join(process.env.NZBGET_UI_CAPTURE_DIR,
            `${tab.toLowerCase()}-${theme}-${width}.jpg`), type: 'jpeg', quality: 90, fullPage: tab === 'Statistics' });
        }
      }
      await page.locator('#DownloadsTabLink').click();
      await page.waitForFunction(() => getComputedStyle(document.querySelector('#DownloadsTab')).opacity === '1');
      // Selection still produces the same queued-group pause request.
      const first = page.locator('#DownloadsTable tbody tr:visible').first();
      await first.locator('.check').click();
      await page.locator('#DownloadsToolbar button[onclick="Downloads.pauseClick()"]:visible').click();
      await check('pause payload', async () => {
        await page.waitForFunction(() => !document.querySelector('#ConfirmDialog')?.classList.contains('in'));
        assert(writes.some(write => write.method === 'editqueue' && write.params[0] === 'GroupPause' && write.params[2].includes(1001)),
          'Selection and pause still reach the original RPC boundary');
      });
      await page.locator('#TBAddButton button').click();
      await page.locator('#AddDialog').waitFor({ state: 'visible' });
      await check('dialog fields', async () => {
        for (const name of ['URL', 'Priority', 'Category']) {
          const input = page.locator(`#AddDialog_${name}`);
          const label = page.locator(`#AddDialog label[for="AddDialog_${name}"]`);
          const a = await label.boundingBox(), b = await input.boundingBox();
          assert(b.y >= a.y + a.height - 1, 'Dialog labels sit above their usable controls');
          assert(b.width >= 100 && b.x + b.width <= width - 8);
        }
        const dialog = await page.locator('#AddDialog').boundingBox();
        assert(dialog.x >= 0 && dialog.x + dialog.width <= width + 1);
        for (const button of await page.locator('#AddDialog .modal-footer .btn:visible').all()) {
          const b = await button.boundingBox(); assert(b.x >= dialog.x && b.x + b.width <= dialog.x + dialog.width + 1);
        }
      });
      if (process.env.NZBGET_UI_CAPTURE_DIR && [1280, 390].includes(width)) {
        await page.screenshot({ path: path.join(process.env.NZBGET_UI_CAPTURE_DIR,
          `add-${theme}-${width}.jpg`), type: 'jpeg', quality: 90 });
      }
      await page.locator('#AddDialog_URL').fill('https://example.invalid/example.nzb');
      await page.locator('#AddDialog_Category').selectOption('Movies');
      await page.locator('#AddDialog_Paused').check();
      await page.locator('#AddDialog_Submit').click();
      await page.locator('#AddDialog').waitFor({ state: 'hidden' });
      await check('add payload', async () => {
        const call = writes.find(write => write.method === 'append');
        assert(call && call.params[1] === 'https://example.invalid/example.nzb' && call.params[2] === 'Movies' && call.params[5] === true);
      });
      await check('page errors', async () => assert.deepEqual(errors, []));
      console.log(`${theme}/${width}: inspected`);
      await context.close();
    }
  } finally { await browser.close(); }
  if (failures.length) throw new Error(failures.join('\n'));
  console.log('All workspace checks: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
