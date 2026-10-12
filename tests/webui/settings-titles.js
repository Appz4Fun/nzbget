const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 const base=new URL(process.argv[2]);assert(['127.0.0.1','localhost'].includes(base.hostname)&&base.port,'Use an isolated loopback fixture');base.hash='settings';
 const browser=await chromium.launch({channel:'chrome'});
 try {for(const locale of ['en','de','tr']) {
  const entries=JSON.parse(fs.readFileSync(locale==='en'?'webui/locales.source.json':`webui/_locales/${locale}/messages.json`));
  const message=key=>typeof entries[key]==='string'?entries[key]:entries[key].message;
  const context=await browser.newContext();await context.addInitScript(l=>localStorage.setItem('Language',l),locale);
  const page=await context.newPage();
  await page.route('**/jsonrpc*',async route=>{const req=route.request().postDataJSON();if(req&&req.method==='readurl')await route.fulfill({json:{result:'[]',error:null}});else await route.continue();});
  await page.goto(base.href);await page.locator('#ConfigNav a[href="#PATHS"]').waitFor({state:'visible'});
  for(const [section,key] of [['Config-Info','nav_info'],['Config-SystemInfo','nav_status'],['Config-System','nav_system'],['Config-Licenses','config_title_licenses'],['extension-manager','config_title_extension_manager']]) {
   // Prime the translation cache, manually change the title, then return twice.
   for(let repeat=0;repeat<2;repeat++) {
    await page.locator(`#ConfigNav a[href="#${section}"]`).press('Enter');
    assert.equal((await page.locator('#ConfigTitle').textContent()).trim(),message(key),`${locale}: ${section} heading matches active section`);
    await page.locator('#ConfigNav a[href="#PATHS"]').press('Enter');
    assert.equal((await page.locator('#ConfigTitle').textContent()).trim(),message('config_section_paths'));
   }
   await page.locator(`#ConfigNav a[href="#${section}"]`).press('Enter');
   assert.equal((await page.locator('#ConfigTitle').textContent()).trim(),message(key));
  }
  await context.close();console.log(`${locale}: PASS (five static sections, repeated returns)`);
 }}finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
