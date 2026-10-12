// Delaying a read-only health reply must not prevent Settings from loading.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const base = new URL(process.argv[2]);
  assert(['127.0.0.1', 'localhost'].includes(base.hostname) && base.port,
    'Use an isolated loopback fixture');
  base.hash = 'settings';
  const browser = await chromium.launch({ channel: 'chrome' });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    let release;
    let held = false;
    const healthReply = new Promise(resolve => { release = resolve; });
    await page.route(/\/jsonrpc(?:\/|$|\?)/, async route => {
      const request = route.request();
      const method = request.method() === 'POST'
        ? request.postDataJSON().method : new URL(request.url()).pathname.split('/').pop();
      if (method === 'systemhealth') {
        held = true;
        await healthReply;
        const response = await route.fetch();
        const body = await response.json();
        const section = body.result.Sections.find(section => section.Name === 'Paths');
        section.Options = section.Options.filter(option => option.Name !== 'MainDir');
        section.Options.push({ Name: 'MainDir', Severity: 'Error', Message: 'Delayed fixture notice' });
        return route.fulfill({ response, json: body });
      }
      await route.continue();
    });
    try {
      await page.goto(base.href);
      await page.locator('#ConfigNav a[href="#PATHS"]').waitFor({ state: 'visible', timeout: 5000 });
      assert(held, 'The health response was held at the actual RPC boundary');
      await page.locator('#ConfigNav a[href="#PATHS"]').press('Enter');
      assert(await page.locator('#S_MainDir').isVisible(), 'Settings is usable before health returns');
      await page.locator('#S_DestDir').fill('${MainDir}/retained edit');
      const row = page.locator('#S_MainDir').locator('xpath=ancestor::div[contains(@class,"control-group")]');
      await row.locator('.config-help-toggle').click();
      assert.deepEqual(errors, []);
      release();
      await page.waitForFunction(() => SystemHealth.getSection('PATHS') !== undefined);
      await row.locator('.option-alert').waitFor({ state: 'visible', timeout: 5000 });
      assert((await row.locator('.option-alert').innerText()).includes('Delayed fixture notice'));
      assert.equal(await page.locator('#ConfigNav a[href="#PATHS"] .badge:visible').innerText(), '1');
      assert.equal(await page.locator('#S_DestDir').inputValue(), '${MainDir}/retained edit');
      assert.equal(await page.locator('#ConfigNav .active a').getAttribute('href'), '#PATHS');
      assert(await row.locator('.help-block').isVisible(), 'Health updates preserve help expansion');
      assert.deepEqual(errors, []);
      console.log('Delayed health reply: PASS');
    } finally { release(); }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
