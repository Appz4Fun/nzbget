// Actual templates/CSS/Bootstrap and merge caller; no daemon or network writes.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { fixtureURL } = require('./workspace-fixture');
const examples = require('./fixtures/workspace.json');

(async () => {
  const base = fixtureURL(process.argv[2]); // Reject live/non-loopback targets before launching.
  const root = path.resolve(__dirname, '../../webui');
  // Keep the committed markup and stylesheet order; omit automatic daemon startup.
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8')
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
  const browser = await chromium.launch({ channel: 'chrome' });
  const failures = [];
  try {
    for (const theme of ['light', 'dark']) for (const width of [1280, 768, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      const page = await context.newPage();
      const errors = [], writes = [];
      page.on('pageerror', e => errors.push(e.message));
      // Fulfill every asset locally. Nothing, including unknown/RPC URLs, reaches a service.
      await page.route('**/*', async route => {
        const url = new URL(route.request().url());
        if (url.origin !== base.origin) return route.abort();
        if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html });
        if (url.pathname === '/combined.css') {
          const files = ['lib/bootstrap.css', 'style.css', 'tokens.css', 'ds.css', 'skin.css'];
          return route.fulfill({ contentType: 'text/css', body: files.map(f => fs.readFileSync(path.join(root, f), 'utf8')).join('\n') });
        }
        const file = path.resolve(root, '.' + decodeURIComponent(url.pathname));
        if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return route.abort();
        return route.fulfill({ path: file });
      });
      await page.goto(base.href);
      await page.addScriptTag({ path: path.join(root, 'lib/jquery.min.js') });
      await page.addScriptTag({ path: path.join(root, 'lib/bootstrap.min.js') });
      await page.addScriptTag({ path: path.join(root, 'i18n.js') });
      await page.evaluate(() => new Promise(resolve => I18n.whenReady(resolve)));
      await page.evaluate(() => I18n.translatePage());
      await page.addScriptTag({ path: path.join(root, 'util.js') });
      await page.addScriptTag({ path: path.join(root, 'edit.js') });
      await page.exposeFunction('recordWrite', call => writes.push(call));
      await page.evaluate(({ theme, width }) => {
        document.documentElement.setAttribute('data-theme', theme);
        document.body.classList.toggle('phone', width < 768);
        document.querySelector('#DownloadsMergeDialog h3').textContent = 'Merge downloads';
        document.querySelector('#DownloadsMergeDialog fieldset > p').textContent = 'Merge these selected example downloads:';
        document.querySelector('#DownloadsMergeDialog .help-block').textContent = 'All selected files will belong to one download.';
        document.querySelector('#LimitDialog h3').textContent = 'Download speed limit';
        document.querySelector('#LimitDialog_SpeedUnit').textContent = 'MB/s';
        document.querySelector('#LimitDialog_SpeedInput').value = '12.5';
        window.UISettings = { setFocus: false };
        window.Refresher = { pause() {}, resume() {}, update() {} };
        window.PopupNotification = { show() {} };
        // Intercept the actual merge handler's RPC; never send it to a daemon.
        RPC.call = (method, params, completed) => { window.recordWrite({ method, params }); completed(); };
        DownloadsMergeDialog.init();
      }, { theme, width });
      async function inspect(name, action) {
        try { await action(); } catch (e) { failures.push(`${theme}/${width}/${name}: ${e.message}`); }
      }
      async function settled(id) {
        await page.locator('#' + id).waitFor({ state: 'visible' });
        await page.evaluate(() => document.fonts.ready);
        await page.waitForFunction(() => !jQuery('.modal:visible, .modal:visible *').is(':animated'));
      }
      async function capture(name) {
        if (process.env.NZBGET_UI_CAPTURE_DIR && [1280, 390].includes(width)) await page.screenshot({
          path: path.join(process.env.NZBGET_UI_CAPTURE_DIR, `${name}-${theme}-${width}.jpg`), type: 'jpeg', quality: 90
        });
      }
      await page.evaluate(groups => DownloadsMergeDialog.showModal([1001, 1002], groups), examples.listgroups);
      await settled('DownloadsMergeDialog');
      const merge = await page.locator('#DownloadsMergeDialog fieldset').evaluate(e => {
        const rect = x => { const r = x.getBoundingClientRect(); return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width }; };
        return { fieldset: rect(e), explanation: rect(e.children[0]), content: rect(e.children[1]), table: rect(e.querySelector('#DownloadsMergeTable')) };
      });
      await inspect('merge full rows', async () => {
        assert(merge.content.y >= merge.explanation.bottom - 1, 'Merge list follows the explanation instead of sitting beside it');
        assert(merge.table.width >= merge.fieldset.width - 2, 'Merge list uses the full available fieldset width');
        assert(merge.table.x >= 0 && merge.table.right <= width, 'Merge list stays inside the viewport');
        const lastName = page.locator('#DownloadsMergeTable table').last().locator('td').last();
        assert.equal(await lastName.innerText(), 'Example Album Lossless');
        const last = await lastName.boundingBox();
        assert(last.x >= merge.table.x && last.x + last.width <= merge.table.right + 1, 'Final merge entry is fully readable');
      });
      await capture('merge');
      await page.locator('#DownloadsMerge_Merge').click();
      await page.locator('#DownloadsMergeDialog').waitFor({ state: 'hidden' });
      await inspect('merge payload', async () => assert.deepEqual(writes, [{ method: 'editqueue', params: ['GroupMerge', '', [1001, 1002]] }]));
      await page.evaluate(() => jQuery('#LimitDialog').modal({ backdrop: 'static' }));
      await settled('LimitDialog');
      const speed = await page.locator('#LimitDialog_SpeedInputGroup').evaluate(e => {
        const rect = x => { const r = x.getBoundingClientRect(); return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, height: r.height }; };
        return { input: rect(e.querySelector('input')), unit: rect(e.querySelector('.add-on')) };
      });
      await inspect('joined speed units', async () => {
        assert(Math.abs(speed.input.y - speed.unit.y) <= 1 && Math.abs(speed.input.bottom - speed.unit.bottom) <= 1,
          'Speed input and unit have matching top and bottom edges');
        assert(Math.abs(speed.input.right - speed.unit.x) <= 1, 'Speed input and unit share a joined border');
      });
      await capture('speed');
      await page.locator('#LimitDialog .close').click();
      await page.evaluate(() => jQuery('#AddDialog').modal({ backdrop: 'static' }));
      await settled('AddDialog');
      await inspect('field grid retained', async () => {
        const boxes = [];
        for (const name of ['URL', 'Priority', 'Category']) {
          const input = await page.locator('#AddDialog_' + name).boundingBox();
          const label = await page.locator(`#AddDialog label[for="AddDialog_${name}"]`).boundingBox();
          assert(input.y >= label.y + label.height - 1, 'Field label stays above its control');
          assert(input.x >= 0 && input.x + input.width <= width, 'Field stays inside viewport');
          boxes.push(input);
        }
        if (width >= 768) assert(Math.abs(boxes[1].y - boxes[2].y) <= 1 && boxes[1].x < boxes[2].x, 'Desktop field controls still share a row');
        else assert(boxes[2].y > boxes[1].y, 'Phone field controls remain stacked');
      });
      await inspect('page errors', async () => assert.deepEqual(errors, []));
      console.log(JSON.stringify({ theme, width, merge, speed, errors }));
      await context.close();
    }
  } finally { await browser.close(); }
  if (failures.length) throw new Error(failures.join('\n'));
  console.log('All affected dialog layout checks: PASS');
})().catch(e => { console.error(e); process.exitCode = 1; });
