// Exercise the real Settings layout only on an isolated loopback daemon.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const base = new URL(process.argv[2]);
  assert(['127.0.0.1', 'localhost'].includes(base.hostname) && base.port,
    'Use an isolated loopback fixture');
  const browser = await chromium.launch({ channel: 'chrome' });
  try {
    for (const theme of ['light', 'dark']) for (const width of [1920, 1280, 1024, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: 1000 } });
      await context.addInitScript(t => localStorage.setItem('Theme', t), theme);
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      base.hash = 'settings';
      await page.goto(base.href);
      try {
        await page.locator('#ConfigNav a[href="#PATHS"]').press('Enter');
      } catch (error) {
        console.error(JSON.stringify({ theme, width, errors,
          activeTab: await page.locator('#NavLinks li.active').innerText(),
          loading: await page.locator('#ConfigLoadInfo').isVisible(),
          loadError: await page.locator('#ConfigLoadError').innerText(),
          connectionError: await page.evaluate(() => UISettings.connectionError) }));
        throw error;
      }
      const main = await page.locator('.config__main').boundingBox();
      if (width >= 1280) {
        assert(width - main.x - main.width <= 35, 'Settings uses the right side of a wide screen');
      }
      const row = page.locator('#S_MainDir').locator('xpath=ancestor::div[contains(@class,"control-group")]');
      const summary = row.locator('.config-option-summary');
      assert.equal(await summary.textContent(), 'Root directory for all tasks.');
      assert.equal(await summary.isVisible(), false, 'Tiles hide short descriptions');
      async function checkTiles(selector) {
        const boxes = await page.locator(selector).evaluateAll(es => es.filter(e => e.getClientRects().length).slice(0, 4).map(e => {
          const tile = e.getBoundingClientRect();
          const label = e.querySelector('.control-label').getBoundingClientRect();
          const control = e.querySelector('.controls').getBoundingClientRect();
          const help = e.querySelector('.config-help-toggle').getBoundingClientRect();
          return { x: tile.x, y: tile.y, width: tile.width, labelBottom: label.bottom,
            controlTop: control.top, controlRight: control.right, tileRight: tile.right,
            labelRight: label.right - parseFloat(getComputedStyle(e.querySelector('.control-label')).paddingRight), helpLeft: help.left };
        }));
        const columns = width >= 1200 ? 3 : width > 768 ? 2 : 1;
        assert(boxes.length >= columns, 'Enough visible tiles to inspect');
        for (let i = 0; i < columns; i++) assert(Math.abs(boxes[i].y - boxes[0].y) < 2, `${columns} complete settings share a row`);
        if (boxes.length > columns) assert(boxes[columns].y > boxes[0].y + 20, 'Next tile wraps to another row');
        for (const box of boxes) {
          assert(box.controlTop >= box.labelBottom - 1, 'Label sits above its control');
          assert(box.controlRight <= box.tileRight + 1, 'Control stays inside tile');
          assert(box.labelRight <= box.helpLeft + 1, 'Help has reserved space beside the label');
        }
      }
      await checkTiles('#ConfigData > .PATHS.control-group');
      await page.locator('#S_MainDir').focus();
      await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(() => document.activeElement.classList.contains('config-help-toggle')), true);
      await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'label:S_DestDir', 'Tab follows source label order');
      await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'S_DestDir', 'Next field follows its label');
      assert((await row.locator('#S_MainDir').boundingBox()).height >= 32, 'Compact fields retain usable height');
      assert.equal(await row.locator('.help-block').isVisible(), false);
      await row.locator('.config-help-toggle').press('Space');
      assert(await row.locator('.help-block').isVisible(), 'Full help remains keyboard accessible');
      await row.locator('.config-help-toggle').click();
      await page.locator('#S_DestDir').fill('${MainDir}/example destination');
      await page.locator('#ConfigNav a[href="#NEWS-SERVERS"]').press('Enter');
      await page.locator('.config-list-row.NEWS-SERVERS .config-list-edit').first().click();
      const serverRow = page.locator('#S_Server1_Name').locator('xpath=ancestor::div[contains(@class,"control-group")]');
      await checkTiles('#ConfigData > .NEWS-SERVERS.control-group');
      await page.locator('#ConfigTable_filter').fill('Server1.Name');
      await page.locator('#ConfigContent.search #S_Server1_Name').waitFor({ state: 'visible' });
      const searchedLabel = await serverRow.locator('.control-label').boundingBox();
      const searchedField = await serverRow.locator('#S_Server1_Name').boundingBox();
      assert(searchedField.y >= searchedLabel.y + searchedLabel.height - 1, 'Search keeps tile label above field');
      await page.locator('#ConfigTable_filter').fill('');
      await page.waitForFunction(() => !document.querySelector('#ConfigContent').classList.contains('search'));
      await page.locator('#ConfigNav a[href="#PATHS"]').press('Enter');
      assert.equal(await page.locator('#S_DestDir').inputValue(), '${MainDir}/example destination');

      // Summaries must display untrusted extension descriptions as text.
      const probe = await page.evaluate(() => {
        const section = { id: 'TABLE-PROBE', multi: false, options: [{
          name: 'PreviewOption', caption: 'PreviewOption', sectionId: 'TABLE-PROBE',
          value: 'example', defvalue: '', select: [],
          description: '<img src=x onerror=alert(1)>\n\nFull help.'
        }] };
        const container = document.createElement('div');
        container.innerHTML = Config.buildOptionsContent(section, false);
        const summary = container.querySelector('.config-option-summary');
        return { text: summary && summary.textContent, images: container.querySelectorAll('img').length };
      });
      assert.equal(probe.text, '<img src=x onerror=alert(1)>');
      assert.equal(probe.images, 0);

      if (process.env.NZBGET_UI_CAPTURE_DIR && width === 1920) {
        // Sanitize every visible path using actual editor inputs before capture.
        await page.locator('#S_MainDir').fill('./downloads');
        for (const input of await page.locator('.PATHS input[type="text"]').all()) {
          const id = await input.getAttribute('id');
          if (id !== 'S_MainDir') await input.fill('${MainDir}/' + id.slice(2).toLowerCase());
        }
        await page.screenshot({ path: path.join(process.env.NZBGET_UI_CAPTURE_DIR,
          `settings-compact-paths-${theme}.jpg`), type: 'jpeg', quality: 90, fullPage: true });
      }
      await page.locator('#ConfigNav a[href="#SECURITY"]').press('Enter');
      await checkTiles('#ConfigData > .SECURITY.control-group');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      if (process.env.NZBGET_UI_CAPTURE_DIR && width === 1920) {
        for (const input of await page.locator('.SECURITY input[type="text"], .SECURITY input[type="password"]').all()) {
          const id = await input.getAttribute('id');
          if (id.includes('Password') || id.includes('Username')) await input.fill('');
          else if (id === 'S_ControlIP' || id === 'S_AuthorizedIP') await input.fill('127.0.0.1');
          else if (id === 'S_SecureCert' || id === 'S_SecureKey') await input.fill('./certs/' + id.slice(2).toLowerCase());
          else if (id === 'S_DaemonUsername') await input.fill('example');
        }
        await page.screenshot({ path: path.join(process.env.NZBGET_UI_CAPTURE_DIR,
          `settings-compact-security-${theme}.jpg`), type: 'jpeg', quality: 90, fullPage: true });
      }
      await page.locator('#DownloadsTabLink').click();
      await page.locator('#LeaveConfigDialog').waitFor({ state: 'visible' });
      assert.equal(await page.locator('#DownloadsTab').isVisible(), false, 'Unsaved changes still guard tab navigation');
      await page.locator('#LeaveConfigDialog .btn-danger').click();
      for (const [link, tab] of [['Downloads', 'Downloads'], ['History', 'History'],
        ['Statistics', 'Statistics'], ['Messages', 'Messages']]) {
        await page.locator(`#${link}TabLink`).click();
        await page.locator(`#${tab}Tab`).waitFor({ state: 'visible' });
        const box = await page.locator(`#${tab}Tab`).boundingBox();
        if (width >= 1280) assert(box.width >= width - 50, `${tab} uses the available width`);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      }
      assert.deepEqual(errors, []);
      await context.close();
      console.log(`${theme}/${width}: PASS`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
