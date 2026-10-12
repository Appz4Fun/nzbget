const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const base=new URL(process.argv[2]);assert(['127.0.0.1','localhost'].includes(base.hostname)&&base.port,'Use an isolated loopback fixture');
 const browser=await chromium.launch({channel:'chrome'});
 try {for(const theme of ['light','dark']) for(const width of [390,1280]) {
  const context=await browser.newContext({viewport:{width,height:844}});
  await context.addInitScript(t=>localStorage.setItem('Theme',t),theme);
  const page=await context.newPage();base.hash='settings';await page.goto(base.href);
  await page.locator('#ConfigNav a[href="#CATEGORIES"]').waitFor({state:'visible'});
  const size=await page.locator('#ConfigNav').evaluate(e=>({height:e.clientHeight,scrollHeight:e.scrollHeight}));
  if(width===390) {assert(size.height<=220,'Phone section menu leaves room for options');assert(size.scrollHeight>size.height);}
  else assert(size.height>400,'Desktop keeps its complete section list');
  const sections=await page.locator('#ConfigNav a').evaluateAll(es=>es.filter(e=>e.getAttribute('href')!=='#Search').map(e=>e.getAttribute('href')));
  // Search selects a section without focusing its navigation link.
  await page.locator('#ConfigTable_filter').fill('UnpackCleanupDisk');
  await page.locator('#ConfigContent.search .option-name').filter({hasText:'UnpackCleanupDisk'}).click();
  assert.equal(await page.locator('#ConfigNav .active a').getAttribute('href'),'#UNPACK');
  if(width===390)assert(await page.locator('#ConfigNav .active a').evaluate(e=>{const n=document.querySelector('#ConfigNav').getBoundingClientRect(),r=e.getBoundingClientRect();return r.top>=n.top-1&&r.bottom<=n.bottom+1;}),'Search-selected section remains inside scroll menu');
  await page.locator('#ConfigTable_filter').fill('');
  for(const href of sections){await page.locator(`#ConfigNav a[href="${href}"]`).press('Enter');assert.equal(await page.locator('#ConfigNav .active a').getAttribute('href'),href);if(width===390){const inside=await page.locator(`#ConfigNav a[href="${href}"]`).evaluate(e=>{const n=document.querySelector('#ConfigNav').getBoundingClientRect(),r=e.getBoundingClientRect();return r.top>=n.top-1&&r.bottom<=n.bottom+1;});assert(inside,'Focused section remains inside scroll menu');}}
  await page.locator('#ConfigNav a[href="#CATEGORIES"]').press('Enter');
  if(width===390)assert((await page.locator('.config-list-row.CATEGORIES').first().boundingBox()).y<650,'Category list appears in first phone screen');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await context.close();console.log(`${theme}/${width}: PASS (${sections.length} sections)`);
 }}finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
