// Real Settings model/editor on an isolated candidate; every mutation intercepted.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { fixtureURL } = require('./workspace-fixture');
const fs = require('node:fs');
const path = require('node:path');

async function installOfflineModel(page, base) {
  const root = path.resolve(__dirname, '../../webui');
  const template = fs.readFileSync(path.resolve(root, '../nzbget.conf'), 'utf8');
  const values = new Map(template.split('\n').filter(line => /^[A-Za-z0-9$].*=/.test(line))
    .map(line => { const eq = line.indexOf('='); return [line.slice(0, eq).trim(), line.slice(eq + 1).trim()]; }));
  for (const [name, value] of Object.entries({ 'Server1.Host': 'example.invalid', 'Server1.Name': 'Example provider',
    'Server1.Username': '', 'Server1.Password': '', ControlUsername: '', ControlPassword: '', DestDir: './fixture/dst' })) values.set(name, value);
  const options = [...values].map(([Name, Value]) => ({ Name, Value }));
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin !== base.origin) return route.abort();
    if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html });
    if (url.pathname === '/jsonrpc') {
      const rpc = route.request().postDataJSON();
      const result = { loadconfig: options, config: options, configtemplates: [{ Name: '', Template: template }], loadextensions: [] }[rpc.method];
      assert.notEqual(result, undefined, 'Offline fixture must account for every read RPC: ' + rpc.method);
      return route.fulfill({ contentType: 'application/json', json: { result, id: rpc.id } });
    }
    if (url.pathname === '/combined.css') return route.fulfill({ contentType: 'text/css', body:
      ['lib/bootstrap.css', 'style.css', 'tokens.css', 'ds.css', 'skin.css'].map(file => fs.readFileSync(path.join(root, file), 'utf8')).join('\n') });
    const file = path.resolve(root, '.' + decodeURIComponent(url.pathname));
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return route.abort();
    return route.fulfill({ path: file });
  });
  return async ({ theme, width }) => {
    for (const file of ['lib/jquery.min.js', 'lib/bootstrap.min.js', 'i18n.js']) await page.addScriptTag({ path: path.join(root, file) });
    await page.evaluate(() => new Promise(resolve => I18n.whenReady(resolve)));
    // Keep actual globals/helpers; omit only automatic application startup.
    const index = fs.readFileSync(path.join(root, 'index.js'), 'utf8');
    const first = index.indexOf('$(document).ready(function()');
    const last = index.indexOf('/*** FRONTEND MAIN PAGE', first);
    assert(first > 0 && last > first);
    await page.addScriptTag({ content: index.slice(0, first) + index.slice(last) });
    for (const file of ['util.js', 'fasttable.js', 'config.js', 'tlscipher.js', 'system-health.js']) await page.addScriptTag({ path: path.join(root, file) });
    await page.evaluate(({ options, theme, width }) => {
      document.documentElement.setAttribute('data-theme', theme);
      document.body.classList.toggle('phone', width < 768);
      UISettings.miniTheme = width < 768;
      Options.options = options;
      RPC.rpcUrl = './jsonrpc';
      Config.init({ updateTabInfo: () => {} });
      Config.show(); Config.shown();
      jQuery('#Navbar, #MainTabContent, #ConfigTab').show();
      jQuery('#ConfigTab').addClass('active');
    }, { options, theme, width });
  };
}

(async () => {
  const base = fixtureURL(process.argv[2]);
  const browser = await chromium.launch({ channel: 'chrome' });
  try {
    for (const theme of ['light', 'dark']) for (const width of [1280, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      await context.addInitScript(value => localStorage.setItem('Theme', value), theme);
      const page = await context.newPage();
      const bootOffline = process.argv.includes('--offline') ? await installOfflineModel(page, base) : null;
      const errors = [], writes = [];
      let state = { Available: true, State: 'idle', JobID: '', Saved: false };
      let completed;
      await page.route(/\/jsonrpc(?:\/|$|\?)/, async route => {
        const request = route.request();
        const url = new URL(request.url());
        const rpc = request.method() === 'POST' ? request.postDataJSON() : { method: url.pathname.split('/').pop(), params: [] };
        if (rpc.method.startsWith('tlscipher')) {
          assert.equal(request.method(), 'POST', 'Optimizer uses authenticated POST RPC');
          writes.push(rpc);
          if (rpc.method === 'tlscipherstart') state = completed;
          return route.fulfill({ contentType: 'application/json', json: { result: state, id: rpc.id } });
        }
        const mutations = ['saveconfig', 'reload', 'shutdown', 'testserver', 'editqueue', 'append', 'scan',
          'pausedownload', 'resumedownload', 'pausepost', 'resumepost', 'pausescan', 'resumescan', 'rate'];
        if (mutations.includes(rpc.method)) {
          writes.push(rpc);
          return route.fulfill({ contentType: 'application/json', json: { result: true, id: rpc.id } });
        }
        return route.fallback();
      });
      page.on('pageerror', error => { errors.push(error.message); console.error('Browser error:', error.message); });
      await page.goto(base.href);
      if (bootOffline) await bootOffline({ theme, width });
      await page.locator('#MainTabContent').waitFor({ state: 'visible' });
      await page.locator('#ConfigTabLink').click();
      await page.locator('#ConfigNav a[href="#NEWS-SERVERS"]').press('Enter');
      const action = page.locator('#Config_OptimizeTls');
      await action.waitFor({ state: 'visible' });
      assert(await action.isEnabled());
      const edit = page.locator('.NEWS-SERVERS.multiid1 .config-list-edit');
      if (await edit.getAttribute('aria-expanded') !== 'true') await edit.press('Enter');
      const host = page.locator('#S_Server1_Host');
      const originalHost = await host.inputValue();
      const originalCipher = await page.locator('#S_Server1_Cipher').inputValue();
      const port = await page.locator('#S_Server1_Port').inputValue();
      const initialSnapshot = await page.evaluate(() => Config.cipherSnapshot());
      if (initialSnapshot === null && bootOffline) {
        console.error('Offline initial server snapshot differences:', await page.evaluate(() => {
          const section = Config.config().flatMap(config => config.sections).find(section => section.id === 'NEWS-SERVERS');
          return { modified: section.modified, differences: section.options.filter(option => !option.template && /^Server\d+\./i.test(option.name))
            .map(option => ({ name: option.name, type: option.type, saved: String((option.value === null ? option.defvalue : option.value) || ''),
              current: String(Config.getOptionValue(option) || '') }))
            .filter(option => option.saved !== option.current && !/Username|Password/i.test(option.name)) };
        }));
      }
      assert.notEqual(initialSnapshot, null);
      await host.fill('unsaved.example.invalid');
      await action.click();
      const dialog = page.locator('#TlsCipherDialog');
      await dialog.waitFor({ state: 'visible' });
      await page.waitForFunction(() => /save.*server/i.test(document.querySelector('#TlsCipherState').textContent));
      assert.match(await page.locator('#TlsCipherState').innerText(), /save.*server/i);
      assert(!writes.some(rpc => rpc.method === 'tlscipherstart'));
      await page.locator('#TlsCipherClose').click();
      await dialog.waitFor({ state: 'hidden' });
      await host.fill(originalHost);

      // Unrelated unsaved fields must survive committing/reconciling ciphers.
      await page.locator('#ConfigNav a[href="#PATHS"]').press('Enter');
      const destination = page.locator('#S_DestDir');
      const changedDestination = (await destination.inputValue()) + '/unsaved-example';
      await destination.fill(changedDestination);
      await page.locator('#ConfigNav a[href="#NEWS-SERVERS"]').press('Enter');
      completed = { Available: true, State: 'completed', JobID: 'example-browser-job', Saved: true, ReloadRequired: true,
        Message: 'Saved fixture cipher.', Servers: [{ ID: 1, Name: 'Example provider', Host: originalHost, Port: Number(port),
          OldCipher: originalCipher, SelectedCipher: 'TLS_AES_128_GCM_SHA256', Outcome: 'saved' }] };
      await action.press('Enter');
      await dialog.waitFor({ state: 'visible' });
      await page.waitForFunction(() => document.querySelector('#S_Server1_Cipher').value === 'TLS_AES_128_GCM_SHA256');
      assert.match(await page.locator('#TlsCipherReload').innerText(), /reload/i);
      assert.equal(await destination.inputValue(), changedDestination);
      assert.notEqual(await page.evaluate(() => Config.cipherSnapshot()), null, 'Confirmed cipher becomes saved browser baseline');
      await page.locator('#TlsCipherClose').press('Enter');
      await dialog.waitFor({ state: 'hidden' });

      // A changed browser server snapshot must reject old completed results.
      const snapshot = await page.evaluate(() => Config.cipherSnapshot());
      if (await edit.getAttribute('aria-expanded') !== 'true') await edit.click();
      await host.fill('changed-during-test.example.invalid');
      assert.equal(await page.evaluate(({ result, snapshot }) => Config.applyCipherResults(result, snapshot),
        { result: completed, snapshot }), false);
      assert.equal(await host.inputValue(), 'changed-during-test.example.invalid');
      assert.equal(await page.locator('#S_Server1_Cipher').inputValue(), 'TLS_AES_128_GCM_SHA256');
      await host.fill(originalHost);

      const saved = page.waitForResponse(response => {
        const request = response.request();
        if (request.method() !== 'POST' || !request.url().includes('/jsonrpc')) return false;
        return request.postDataJSON().method === 'saveconfig';
      });
      await page.locator('#Config_Save:visible').click();
      await saved;
      const save = writes.find(rpc => rpc.method === 'saveconfig');
      assert(save, 'Actual Settings Save reaches intercepted RPC boundary');
      assert(save.params[0].some(option => option.Name === 'Server1.Cipher' && option.Value === 'TLS_AES_128_GCM_SHA256'));
      assert(save.params[0].some(option => option.Name === 'DestDir' && option.Value === changedDestination));
      assert.equal(writes.filter(rpc => rpc.method === 'tlscipherstart').length, 1);
      assert.deepEqual(errors, []);
      await context.close();
    }
    process.stdout.write('TLS cipher real Settings integration: four cases passed\n');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
