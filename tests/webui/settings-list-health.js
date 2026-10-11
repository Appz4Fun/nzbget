// Read-only fixture responses simulate option-level health notices for each list type.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const base = process.argv[2];
  assert(base && /^http:\/\/(127\.0\.0\.1|localhost):/.test(base), 'Use a loopback fixture');
  const browser = await chromium.launch({channel: 'chrome'});
  try {
    for (const width of [1280, 390]) {
      const page = await browser.newPage({viewport:{width,height:844}});
      await page.route(/\/jsonrpc(?:\/|$|\?)/, async route => {
        const req = route.request().method() === 'POST' ? route.request().postDataJSON() : {method:new URL(route.request().url()).pathname.split('/').pop()};
        if (!req || !['config', 'loadconfig', 'systemhealth'].includes(req.method)) return route.continue();
        const response = await route.fetch();
        const body = await response.json();
        if (req.method === 'systemhealth') {
          for (const [name, prefix, fields] of [['Categories','Category',['Name','Aliases']], ['Feeds','Feed',['URL','Interval']], ['Scheduler','Task',['Time','Param']]]) {
            body.result.Sections = body.result.Sections.filter(s => s.Name !== name);
            body.result.Sections.push({Name:name,Issues:[],Subsections:[],Options:fields.map((field,i) => ({Name:prefix+'1.'+field,Severity:i ? 'Warning':'Error',Message:'Fixture notice '+i}))});
          }
        } else {
          const values = {'SystemHealthCheck':'yes','Feed1.Name':'Health feed','Feed1.URL':'https://example.invalid/feed','Feed1.Interval':'15','Task1.Time':'08:00','Task1.WeekDays':'1-7','Task1.Command':'PauseDownload','Task1.Param':''};
          for (const [Name,Value] of Object.entries(values)) {
            const existing = body.result.find(o => o.Name === Name);
            if (existing) existing.Value = Value; else body.result.push({Name,Value});
          }
        }
        await route.fulfill({response,json:body});
      });
      await page.goto(base);
      await page.locator('#ConfigTabLink').click();
      for (const section of ['CATEGORIES','RSS_FEEDS','SCHEDULER']) {
        await page.locator(`#ConfigNav a[href="#${section}"]`).press('Enter');
        const row = page.locator(`.config-list-row.${section}.multiid1`);
        assert.equal(await row.locator('.config-list-edit').getAttribute('aria-expanded'), 'false');
        assert.equal(await row.locator('.config-list-health').isVisible(), true, `${section}: closed row exposes health notices`);
        assert.match(await row.locator('.config-list-health').textContent(), /^2 /);
        await row.locator('.config-list-edit').press('Enter');
        assert.equal(await page.locator(`.config-list-detail.${section}.multiid1 .option-alert:visible`).count(), 2);
        await row.locator('.config-list-edit').press('Space');
        assert.equal(await row.locator('.config-list-health').isVisible(), true);
      }
      await page.close();
      console.log(`${width}: PASS`);
    }
  } finally {await browser.close();}
})().catch(e => {console.error(e.message);process.exitCode=1;});
