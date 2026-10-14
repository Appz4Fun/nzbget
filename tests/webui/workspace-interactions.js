// Real clicks and keyboard navigation; example RPC replies, intercepted writes.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const { fixtureURL, installFixture } = require('./workspace-fixture');

(async () => {
  const base = fixtureURL(process.argv[2]);
  const browser = await chromium.launch({ channel: 'chrome' });
  try {
    for (const theme of ['light', 'dark']) for (const width of [1280, 768, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      await context.addInitScript(t => localStorage.setItem('Theme', t), theme);
      const page = await context.newPage();
      const writes = [], errors = [], fixture = { groups: 13 };
      await installFixture(page, writes, fixture);
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(base.href);
      await page.locator('#DownloadsTable tbody tr').first().waitFor();
      async function tab(name) {
        const link = page.locator(`#${name}TabLink`);
        await link.focus();
        await page.keyboard.press('Enter');
        await page.waitForFunction(id => document.getElementById(id).classList.contains('active') &&
          getComputedStyle(document.getElementById(id)).opacity === '1', `${name}Tab`);
      }
      async function dialogBounds(id, captureName = id) {
        const dialog = page.locator(`#${id}`);
        await dialog.waitFor({ state: 'visible' });
        await page.waitForFunction(() => !jQuery('.modal:visible, .modal:visible *').is(':animated'));
        await page.waitForFunction(() => !jQuery('[id^=Notif_]').is(':visible'));
        await page.evaluate(() => document.fonts.ready);
        const box = await dialog.boundingBox();
        assert(box.x >= 0 && box.x + box.width <= width + 1, `${id} stays within viewport`);
        const body = dialog.locator('.modal-body');
        assert(await body.evaluate(e => e.scrollWidth <= e.clientWidth + 1), `${id} has no clipped horizontal content`);
        for (const control of await dialog.locator('input:visible, select:visible, .modal-footer .btn:visible').all()) {
          const b = await control.boundingBox();
          assert(b.x >= box.x && b.x + b.width <= box.x + box.width + 1, `${id} control stays in dialog`);
        }
        if (process.env.NZBGET_UI_CAPTURE_DIR && width !== 320) await page.screenshot({
          path: path.join(process.env.NZBGET_UI_CAPTURE_DIR, `${captureName.toLowerCase()}-${theme}-${width}.jpg`),
          type: 'jpeg', quality: 90
        });
      }
      if (width === 1280) for (const resized of [390, 1280]) {
        await page.setViewportSize({ width: resized, height: 900 });
        await page.waitForFunction(w => document.querySelector('#DownloadsRecordsPerPageBlock').parentElement.id ===
          (w < 768 ? 'DownloadsRecordsPerPageBlockPhone' : 'DownloadsTableTopBlock'), resized);
        assert.equal(await page.locator('#DownloadsRecordsPerPage:visible').count(), 1, 'Page size control survives breakpoint changes');
        assert.equal(await page.locator('#DownloadsTable_pager:visible').count(), 1, 'Pager survives breakpoint changes');
      }
      function holdSave(command, dialogId, transmitId) {
        let release;
        fixture.holdMutation = rpc => rpc.method === 'editqueue' && rpc.params[0] === command ?
          new Promise(resolve => { release = resolve; }) : Promise.resolve();
        return async () => {
          try {
            const transmit = page.locator(`#${transmitId}`);
            await transmit.waitFor({ state: 'visible' }); // The real caller's 500ms pending indicator.
            const spinner = await transmit.boundingBox();
            const footer = page.locator(`#${dialogId} .modal-footer`);
            const box = await footer.boundingBox();
            assert(spinner.x >= box.x && spinner.x + spinner.width <= box.x + box.width &&
              spinner.y >= box.y && spinner.y + spinner.height <= box.y + box.height,
              'Pending-save indicator stays inside the footer');
            for (const button of await footer.locator('.btn:visible').all()) {
              assert.equal(await button.getAttribute('disabled'), 'disabled', 'Real pending caller disables actions');
              const b = await button.boundingBox();
              const overlapX = Math.min(b.x + b.width, spinner.x + spinner.width) - Math.max(b.x, spinner.x);
              const overlapY = Math.min(b.y + b.height, spinner.y + spinner.height) - Math.max(b.y, spinner.y);
              assert(overlapX <= 0 || overlapY <= 0, 'Pending-save indicator never covers button labels');
            }
          } finally {
            if (release) release();
            fixture.holdMutation = undefined;
          }
        };
      }
      assert.equal(await page.locator('#DownloadsTable tbody tr:visible').count(), 10);
      await page.locator('#DownloadsTable_pager a').last().click();
      await page.waitForFunction(() => document.querySelectorAll('#DownloadsTable tbody tr').length === 3);
      assert.match(await page.locator('#DownloadsTable tbody').innerText(), /Example archive 13/);
      await page.locator('#DownloadsTable_pager a').first().click();
      await page.locator('#DownloadsTable tbody a[data-nzbid="1001"]').focus();
      await page.keyboard.press('Enter');
      await dialogBounds('DownloadsEditDialog');
      const lastAction = page.locator('#DownloadsEdit_Log');
      await lastAction.scrollIntoViewIfNeeded();
      const lastBox = await lastAction.boundingBox();
      const bodyBox = await page.locator('#DownloadsEditDialog .modal-body').boundingBox();
      assert(lastBox.y >= bodyBox.y && lastBox.y + lastBox.height <= bodyBox.y + bodyBox.height,
        'The final editor action is reachable in the scrolling body');
      if (process.env.NZBGET_UI_CAPTURE_DIR && width !== 320) await page.screenshot({
        path: path.join(process.env.NZBGET_UI_CAPTURE_DIR, `downloadsedit-last-${theme}-${width}.jpg`), type: 'jpeg', quality: 90
      });
      await page.locator('#DownloadsEdit_NZBName').fill('Renamed example');
      const finishDownloadSave = holdSave('GroupSetName', 'DownloadsEditDialog', 'DownloadsEdit_Transmit');
      await page.locator('#DownloadsEdit_Save').click();
      await finishDownloadSave();
      await page.locator('#DownloadsEditDialog').waitFor({ state: 'hidden' });
      assert(writes.some(w => w.method === 'editqueue' && w.params[0] === 'GroupSetName' &&
        w.params[1] === 'Renamed example' && w.params[2][0] === 1001));
      if (width >= 768) {
        await page.locator('#DownloadsTable tbody tr').first().locator('td').nth(1).locator('[data-nzbid]').click();
        await page.locator('#PriorityMenu').waitFor({ state: 'visible' });
        const box = await page.locator('#PriorityMenu').boundingBox();
        assert(box.x >= 0 && box.x + box.width <= width, 'Row menu is not clipped by the table scroll area');
        await page.locator('#PriorityMenu li[data="50"] a').click();
        assert(writes.some(w => w.method === 'editqueue' && w.params[0] === 'GroupSetPriority' && w.params[1] === '50'));
      }
      await tab('History');
      await page.locator('#HistoryTable tbody a[data-nzbid="2001"]').click();
      await dialogBounds('HistoryEditDialog');
      await page.locator('#HistoryEdit_NZBName').fill('Renamed history example');
      const finishHistorySave = holdSave('HistorySetName', 'HistoryEditDialog', 'HistoryEdit_Transmit');
      await page.locator('#HistoryEdit_Save').click();
      await finishHistorySave();
      await page.locator('#HistoryEditDialog').waitFor({ state: 'hidden' });
      assert(writes.some(w => w.method === 'editqueue' && w.params[0] === 'HistorySetName' &&
        w.params[1] === 'Renamed history example' && w.params[2][0] === 2001));
      await page.locator('#HistoryTab button[onclick="History.filter(\'FAILURE\')"]:visible').click();
      assert.equal(await page.locator('#HistoryTable tbody tr:visible').count(), 1);
      assert.match(await page.locator('#HistoryTable tbody').innerText(), /FAILURE/);
      await tab('Messages');
      await page.locator('#MessagesTab button[onclick="Messages.filter(\'ERROR\')"]:visible').click();
      assert.equal(await page.locator('#MessagesTable tbody tr:visible').count(), 1);
      assert.match(await page.locator('#MessagesTable tbody').innerText(), /Example article/);
      await page.locator('#StatusTime').click();
      await dialogBounds('StatDialog');
      await page.locator('#StatDialog_Volumes').click();
      await page.locator('#StatDialog_Chart svg').first().waitFor();
      await dialogBounds('StatDialog', 'stat-volumes');
      await page.locator('#StatDialog_Back').click();
      await page.locator('#StatDialog_GeneralTab').waitFor({ state: 'visible' });
      await page.locator('#StatDialog .close').click();
      fixture.empty = true;
      await page.reload();
      await tab('Downloads');
      await page.locator('#DownloadQueueEmpty').waitFor({ state: 'visible' });
      const empty = await page.locator('#DownloadQueueEmpty').boundingBox();
      assert(empty.x >= 0 && empty.x + empty.width <= width);
      await tab('History');
      assert.equal(await page.locator('#HistoryTable tbody a[data-nzbid]').count(), 0);
      await tab('Messages');
      assert.equal(await page.locator('#MessagesTable tbody tr').count(), 0);
      assert.deepEqual(errors, []);
      console.log(`${theme}/${width}: paging, keyboard, menus, editors, payloads, filters, statistics, empty views PASS`);
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
