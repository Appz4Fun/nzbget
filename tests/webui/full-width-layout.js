// Real layout regression: desktop Settings must grow with the window, not center a capped form.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const base=new URL(process.argv[2]);assert(['127.0.0.1','localhost'].includes(base.hostname)&&base.port,'Use an isolated loopback fixture');
 const browser=await chromium.launch({channel:'chrome'});
 try {for(const theme of ['light','dark']){
  const context=await browser.newContext({viewport:{width:1280,height:900}});
  await context.addInitScript(t=>localStorage.setItem('Theme',t),theme);
  const page=await context.newPage();base.hash='settings';await page.goto(base.href);
  await page.locator('#ConfigNav a[href="#CATEGORIES"]').waitFor({state:'visible'});
  let previousWidth=0,previousAvailableWidth=0,railWidth=0;
  for(const width of [769,800,1024,1280,1920,2560]){
   await page.setViewportSize({width,height:900});
   await page.locator('#ConfigNav a[href="#CATEGORIES"]').press('Enter');
   await page.locator('.config__main').waitFor({state:'visible'});
   const rail=await page.locator('.config__aside').boundingBox(),main=await page.locator('.config__main').boundingBox(),container=await page.locator('#MainContent').boundingBox(),layout=await page.locator('.config__container').boundingBox();
   assert(rail.x-container.x<24,'Settings navigation stays at the left edge');
   assert(main.x+main.width>=width-36,'Settings content reaches the right edge');
   assert(main.x>=rail.x+rail.width&&main.x-rail.x-rail.width<=24,'Content remains beside navigation');
   if(previousWidth){assert(main.width-previousWidth>=layout.width-previousAvailableWidth-2,'Extra available desktop width belongs to the content');assert(Math.abs(rail.width-railWidth)<2,'Navigation width stays stable');}
   previousWidth=main.width;previousAvailableWidth=layout.width;railWidth=rail.width;
   await page.locator('#ConfigNav a[href="#PATHS"]').press('Enter');
   const fieldsFit=await page.locator('.control-group.PATHS input[type="text"]').evaluateAll(es=>{const right=document.querySelector('.config__main').getBoundingClientRect().right,visible=es.filter(e=>e.getBoundingClientRect().width>0);return visible.length>0&&visible.every(e=>e.getBoundingClientRect().right<=right);});
   assert(fieldsFit,'Path editors remain inside the narrow desktop content pane');
   await page.locator('#ConfigNav a[href="#Config-SystemInfo"]').press('Enter');
   await page.locator('.config-status').waitFor({state:'visible'});
   const status=await page.locator('.config-status').boundingBox();assert(status.x+status.width>=width-40,'Status panels fill the content area');
   await page.locator('#StatisticsTabLink').click();
   // The packaged fixture may offer unsaved defaults from this fork's newer template.
   // Discard browser-only defaults; never save them to the fixture daemon.
   if(await page.locator('#LeaveConfigDialog').isVisible())await page.locator('#LeaveConfigDialog .btn-danger').click();
   await page.locator('#StatisticsTab').waitFor({state:'visible'});
   const stats=await page.locator('#StatisticsTab').boundingBox();assert(stats.x<24&&stats.x+stats.width>=width-24,'Statistics fills the desktop');
   await page.locator('#ConfigTabLink').click();
   await page.locator('.config__main').waitFor({state:'visible'});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'No horizontal page overflow');
   console.log(`${theme}/${width}: full-width PASS`);
  }
  await page.setViewportSize({width:390,height:844});await page.locator('#ConfigNav a[href="#CATEGORIES"]').press('Enter');
  assert((await page.locator('.config-list-row.CATEGORIES').first().boundingBox()).y<650,'Phone category list remains in first screen');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await context.close();
 }}finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
