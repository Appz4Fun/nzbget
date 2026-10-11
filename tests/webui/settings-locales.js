const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

(async () => {
  const base = process.argv[2];
  assert(base && /^http:\/\/(127\.0\.0\.1|localhost):/.test(base), 'Use a loopback fixture');
  const source = JSON.parse(fs.readFileSync('webui/locales.source.json'));
  assert(source.config_server_issues, 'Server health count has a catalog entry');
  for (const locale of Object.keys(source.__LOCALES__).filter(l => l !== 'en')) {
    const entries = JSON.parse(fs.readFileSync(`webui/_locales/${locale}/messages.json`));
    assert(entries.config_server_issues && entries.stat_server_connections && entries.btn_quick_help, `${locale}: labels translated`);
  }
  const browser = await chromium.launch({ channel: 'chrome' });
  try {
    for (const locale of ['de', 'es', 'tr']) {
      const entries = JSON.parse(fs.readFileSync(`webui/_locales/${locale}/messages.json`));
      const context = await browser.newContext();
      await context.addInitScript(l => localStorage.setItem('Language', l), locale);
      const page = await context.newPage();
      await page.goto(base);
      await page.locator('#ConfigTabLink').click();
      await page.locator('#ConfigNav a[href="#NEWS-SERVERS"]').press('Enter');
      assert((await page.locator('.config-server-connections').first().innerText()).includes(entries.stat_server_connections));
      const health = await page.locator('.config-server-health').first().innerText();
      if (health) assert(health.includes(entries.config_server_issues));
      await page.locator('.config-server-edit').first().click();
      assert((await page.locator('.NEWS-SERVERS .config-help-toggle').first().getAttribute('aria-label')).includes(entries.btn_quick_help));
      await context.close();
      console.log(`${locale}: PASS`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
