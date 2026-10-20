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
  const boot = async ({ theme, width }) => {
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
  boot.setSavedValue = (name, value) => {
    const option = options.find(option => option.Name === name);
    if (option) option.Value = value;
    else options.push({ Name: name, Value: value });
  };
  return boot;
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
      let running, completionVisible = true, failNextStart = false;
      let rejectStaleSave = false, diskBaseline = '';
      await page.route(/\/jsonrpc(?:\/|$|\?)/, async route => {
        const request = route.request();
        const url = new URL(request.url());
        const rpc = request.method() === 'POST' ? request.postDataJSON() : { method: url.pathname.split('/').pop(), params: [] };
        if (rpc.method.startsWith('tlscipher')) {
          assert.equal(request.method(), 'POST', 'Optimizer uses authenticated POST RPC');
          writes.push(rpc);
          if (rpc.method === 'tlscipherstart') {
            if (failNextStart) {
              failNextStart = false;
              state = { Available: true, State: 'idle', JobID: '', Saved: false };
              return route.fulfill({ contentType: 'application/json', json: {
                error: { code: 3, message: 'Fixture start rejected.' }, id: rpc.id } });
            }
            state = running = { ...completed, State: 'probing', Saved: false, ReloadRequired: false, Servers: [] };
          }
          if (rpc.method === 'tlscipherstatus' && rpc.params.length) assert.equal(rpc.params[0], state.JobID);
          const result = state.State === 'completed' && !completionVisible ? running : state;
          return route.fulfill({ contentType: 'application/json', json: { result, id: rpc.id } });
        }
        const mutations = ['saveconfig', 'reload', 'shutdown', 'testserver', 'editqueue', 'append', 'scan',
          'pausedownload', 'resumedownload', 'pausepost', 'resumepost', 'pausescan', 'resumescan', 'rate'];
        if (mutations.includes(rpc.method)) {
          writes.push(rpc);
          if (rpc.method === 'saveconfig' && rejectStaleSave) {
            const metadata = rpc.params[0].find(option => option.Name === '_TlsCipherBaseline');
            if (metadata) assert.notEqual(metadata.Value, diskBaseline, 'Fixture models a different browser committing first');
            return route.fulfill({ contentType: 'application/json', json: { id: rpc.id,
              error: { code: 3, message: 'News server settings changed in another operation. Refresh Settings before saving; your edits have been retained.' } } });
          }
          return route.fulfill({ contentType: 'application/json', json: { result: true, id: rpc.id } });
        }
        return route.fallback();
      });
      page.on('pageerror', error => { errors.push(error.message); console.error('Browser error:', error.message); });
      await page.goto(base.href);
      if (bootOffline) await bootOffline({ theme, width });
      // Observe the real synchronous RPC dispatch as well as intercepted
      // transport, so no-save assertions cannot race request delivery.
      await page.evaluate(() => {
        window.cipherSaveRequests = [];
        const call = RPC.call;
        RPC.call = function(method, params) {
          if (method === 'saveconfig') window.cipherSaveRequests.push(params);
          return call.apply(this, arguments);
        };
      });
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
      const initialValues = await page.evaluate(() => Config.config().values);
      const canonical = values => {
        const fields = new Map();
        for (const option of values) if (/^Server[1-9][0-9]*\.(Host|Port|Cipher)$/i.test(option.Name))
          fields.set(option.Name.toLowerCase(), Buffer.from(option.Value, 'utf8').toString('hex'));
        return 'v1\n' + [...fields].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([name, value]) => name + '=' + value + '\n').join('');
      };
      diskBaseline = canonical(initialValues);
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
      await page.waitForFunction(() => document.querySelector('#TlsCipherCancel').disabled === false);
      await page.locator('#TlsCipherClose').press('Enter');
      await dialog.waitFor({ state: 'hidden' });
      // Completion may happen before the next poll. Neither an active nor an
      // unobserved completed job may let a full save restore stale ciphers.
      completionVisible = false;
      state = completed;
      await page.evaluate(() => Config.saveChanges());
      assert.equal(await page.evaluate(() => cipherSaveRequests.length), 0,
        'A full save must not send stale ciphers after a hidden job commits');
      completionVisible = true;
      await page.waitForFunction(() => document.querySelector('#S_Server1_Cipher').value === 'TLS_AES_128_GCM_SHA256');
      assert.equal(await dialog.isVisible(), false, 'A hidden job reconciles without reopening the dialog');
      await action.press('Enter');
      await dialog.waitFor({ state: 'visible' });
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

      // A saved result that conflicts with intervening server edits must keep
      // ordinary saves blocked rather than silently overwrite the disk cipher.
      state = { Available: true, State: 'idle', JobID: '', Saved: false };
      completed = { ...completed, JobID: 'example-browser-conflict', Servers: [{ ...completed.Servers[0],
        OldCipher: 'TLS_AES_128_GCM_SHA256', SelectedCipher: 'TLS_AES_256_GCM_SHA384' }] };
      await page.evaluate(() => TlsCipherDialog.showModal());
      await dialog.waitFor({ state: 'visible' });
      await page.waitForFunction(() => document.querySelector('#TlsCipherCancel').disabled === false);
      await page.locator('#TlsCipherClose').click();
      await dialog.waitFor({ state: 'hidden' });
      await host.fill('changed-during-second-job.example.invalid');
      await page.evaluate(() => Config.saveChanges());
      assert.equal(await page.evaluate(() => cipherSaveRequests.length), 0, 'Active jobs block full saves');
      state = completed;
      await page.waitForFunction(() => /server editor changed/.test(document.querySelector('#TlsCipherState').textContent));
      await page.evaluate(() => Config.saveChanges());
      assert.equal(await page.evaluate(() => cipherSaveRequests.length), 0, 'Unreconciled results block stale full saves');
      assert.equal(await host.inputValue(), 'changed-during-second-job.example.invalid');
      // Reverting the intervening edit lets the real model reconcile again.
      await host.fill(originalHost);
      await action.press('Enter');
      await dialog.waitFor({ state: 'visible' });
      await page.waitForFunction(() => document.querySelector('#S_Server1_Cipher').value === 'TLS_AES_256_GCM_SHA384');
      await page.locator('#TlsCipherClose').click();
      await dialog.waitFor({ state: 'hidden' });

      // An RPC failure is uncertain until status confirms no admitted job.
      // Confirm idle without auto-retrying, then allow the unrelated save.
      state = { Available: true, State: 'idle', JobID: '', Saved: false };
      failNextStart = true;
      await action.press('Enter');
      await dialog.waitFor({ state: 'visible' });
      await page.waitForFunction(() => /Fixture start rejected/.test(document.querySelector('#TlsCipherState').textContent));
      await page.evaluate(() => Config.saveChanges());
      assert.equal(await page.evaluate(() => cipherSaveRequests.length), 0);
      await page.locator('#TlsCipherAgain').click();
      await page.waitForFunction(() => TlsCipherDialog.canSaveSettings());
      assert.equal(writes.filter(rpc => rpc.method === 'tlscipherstart').length, 3, 'Retry must recover idle without starting');
      // Also preserve recovery when the failed request is followed by closing
      // and reopening rather than using the in-dialog retry control.
      failNextStart = true;
      await page.locator('#TlsCipherAgain').click();
      await page.waitForFunction(() => /Fixture start rejected/.test(document.querySelector('#TlsCipherState').textContent));
      await page.locator('#TlsCipherClose').click();
      await dialog.waitFor({ state: 'hidden' });
      await page.evaluate(() => Config.saveChanges());
      assert.equal(await page.evaluate(() => cipherSaveRequests.length), 0);
      await action.press('Enter');
      await dialog.waitFor({ state: 'visible' });
      await page.waitForFunction(() => TlsCipherDialog.canSaveSettings());
      assert.equal(writes.filter(rpc => rpc.method === 'tlscipherstart').length, 4, 'Idle recovery must not start again');
      await page.locator('#TlsCipherClose').click();
      await dialog.waitFor({ state: 'hidden' });

      rejectStaleSave = true;
      await page.locator('#Config_Save:visible').click();
      assert(await page.evaluate(() => cipherSaveRequests[cipherSaveRequests.length - 1][0]
        .some(option => option.Name === '_TlsCipherBaseline')), 'Ordinary saves must include the saved server baseline');
      await page.waitForFunction(() => document.querySelector('#Notif_Config_CipherPending strong').textContent.includes('another operation'));
      assert.equal(await destination.inputValue(), changedDestination, 'Rejected stale saves retain unrelated edits');
      assert(await page.locator('#Config_Save:visible').isEnabled());
      const rejected = writes.find(rpc => rpc.method === 'saveconfig');
      assert(rejected.params[0].some(option => option.Name === '_TlsCipherBaseline'), 'Actual full-save transport carries CAS metadata');
      const parity = [{ Name: 'Server1.Host', Value: 'h\u00e9' }, { Name: 'Server1.Cipher', Value: 'old' },
        { Name: 'server1.cipher', Value: '' }, { Name: 'Server1.Port', Value: '563' }, { Name: 'Server01.Host', Value: 'ignored' }];
      assert.equal(await page.evaluate(values => Config.cipherBaseline(values), parity),
        'v1\nserver1.cipher=\nserver1.host=68c3a9\nserver1.port=353633\n');
      assert.equal(rejected.params[0].find(option => option.Name === '_TlsCipherBaseline').Value,
        canonical(await page.evaluate(() => Config.config().values)), 'Reconciled cipher becomes the saved CAS baseline');
      rejectStaleSave = false;
      const saved = page.waitForResponse(response => {
        const request = response.request();
        if (request.method() !== 'POST' || !request.url().includes('/jsonrpc')) return false;
        return request.postDataJSON().method === 'saveconfig';
      });
      await page.locator('#Config_Save:visible').click();
      assert.equal((await (await saved).json()).result, true, 'The retry must actually succeed');
      const save = writes.filter(rpc => rpc.method === 'saveconfig').slice(-1)[0];
      assert(save, 'Actual Settings Save reaches intercepted RPC boundary');
      assert(save.params[0].some(option => option.Name === 'Server1.Cipher' && option.Value === 'TLS_AES_256_GCM_SHA384'));
      assert(save.params[0].some(option => option.Name === 'DestDir' && option.Value === changedDestination));
      assert.equal(save.params[0].find(option => option.Name === '_TlsCipherBaseline').Value,
        canonical(await page.evaluate(() => Config.config().values)));
      assert.equal(writes.filter(rpc => rpc.method === 'tlscipherstart').length, 4);
      assert.deepEqual(errors, []);
      await context.close();
    }
    if (process.argv.includes('--offline')) {
      // Real Settings reads after a page reload and a same-tab refresh. The
      // daemon retains a completed job while saved config already has its result.
      for (const theme of ['light', 'dark']) for (const width of [1280, 390]) {
        const context = await browser.newContext({ viewport: { width, height: 900 } });
        const page = await context.newPage();
        const boot = await installOfflineModel(page, base);
        const selected = 'TLS_AES_256_GCM_SHA384', other = 'TLS_CHACHA20_POLY1305_SHA256';
        boot.setSavedValue('Server1.Port', '563');
        boot.setSavedValue('Server1.Cipher', selected);
        boot.setSavedValue('Server2.Host', 'second.example.invalid');
        boot.setSavedValue('Server2.Port', '563');
        boot.setSavedValue('Server2.Cipher', other);
        const result = { Available: true, State: 'completed', JobID: 'retained-saved-job', Saved: true,
          ReloadRequired: true, Message: 'Saved fixture cipher.', Servers: [{ ID: 1, Name: 'Example provider',
            Host: 'example.invalid', Port: 563, OldCipher: 'TLS_AES_128_GCM_SHA256',
            SelectedCipher: selected, Outcome: 'saved' }] };
        const writes = [], errors = [];
        let holdNextStatus = false, releaseStatus;
        let statusEntered;
        const statusHeld = new Promise(resolve => { statusEntered = resolve; });
        page.on('pageerror', error => errors.push(error.message));
        await page.route(/\/jsonrpc(?:\/|$|\?)/, async route => {
          const rpc = route.request().postDataJSON();
          if (rpc.method.startsWith('tlscipher')) {
            assert.equal(rpc.method, 'tlscipherstatus', 'Reopening a retained job must not start another test');
            if (rpc.params.length) assert.equal(rpc.params[0], result.JobID);
            if (holdNextStatus) {
              holdNextStatus = false;
              statusEntered();
              await new Promise(resolve => { releaseStatus = resolve; });
            }
            return route.fulfill({ contentType: 'application/json', json: { result, id: rpc.id } });
          }
          if (rpc.method === 'saveconfig') {
            writes.push(rpc);
            return route.fulfill({ contentType: 'application/json', json: { result: true, id: rpc.id } });
          }
          return route.fallback();
        });
        async function newsEditor() {
          await page.locator('#ConfigNav a[href="#NEWS-SERVERS"]').press('Enter');
          const edit = page.locator('.NEWS-SERVERS.multiid1 .config-list-edit');
          if (await edit.getAttribute('aria-expanded') !== 'true') await edit.press('Enter');
          await page.locator('#S_Server1_Cipher').waitFor({ state: 'visible' });
        }
        await page.goto(base.href);
        await boot({ theme, width });
        await newsEditor();
        const loadedSnapshot = await page.evaluate(() => Config.cipherSnapshot());
        const loadedValues = await page.evaluate(() => JSON.stringify(Config.config().values));
        assert.notEqual(loadedSnapshot, null);
        assert.equal(await page.evaluate(({ result, snapshot }) => Config.applyCipherResults(result, snapshot),
          { result, snapshot: loadedSnapshot }), true, 'A freshly loaded selected cipher is already reconciled');
        assert.equal(await page.evaluate(result => Config.applyCipherResults(result, null), result), true,
          'A clean persisted selected cipher needs no captured pre-job snapshot');
        assert.equal(await page.evaluate(({ result, snapshot }) => Config.applyCipherResults(result, snapshot),
          { result, snapshot: loadedSnapshot }), true, 'Repeated completed results are idempotent');
        assert.equal(await page.evaluate(() => JSON.stringify(Config.config().values)), loadedValues,
          'Already reconciled values remain byte-identical in the saved browser model');
        for (const [id, changed, original] of [['Host', 'edited.example.invalid', 'example.invalid'],
          ['Port', '564', '563'], ['Cipher', other, selected]]) {
          const field = page.locator('#S_Server1_' + id);
          await field.fill(changed);
          assert.equal(await page.evaluate(({ result, snapshot }) => Config.applyCipherResults(result, snapshot),
            { result, snapshot: loadedSnapshot }), false, 'Unsaved server edits remain conflicts: ' + id);
          assert.equal(await field.inputValue(), changed);
          await field.fill(original);
        }
        for (const identity of [{ Host: 'different.example.invalid' }, { Port: 564 }]) {
          const mismatch = { ...result, Servers: [{ ...result.Servers[0], ...identity }] };
          assert.equal(await page.evaluate(({ result, snapshot }) => Config.applyCipherResults(result, snapshot),
            { result: mismatch, snapshot: loadedSnapshot }), false, 'Clean selected values still require the exact server identity');
        }

        const mixed = { ...result, Servers: [result.Servers[0], { ID: 2, Name: 'Second provider',
          Host: 'second.example.invalid', Port: 563, OldCipher: 'TLS_AES_128_GCM_SHA256',
          SelectedCipher: other, Outcome: 'saved' }] };
        async function refreshSettings() {
          await page.evaluate(() => { Config.hide(); Config.show(); Config.shown(); });
          await newsEditor();
        }
        // A mixed result can patch old values only with an unchanged whole
        // snapshot, while other rows may already contain their saved choice.
        boot.setSavedValue('Server1.Cipher', result.Servers[0].OldCipher);
        await refreshSettings();
        const mixedSnapshot = await page.evaluate(() => Config.cipherSnapshot());
        assert.equal(await page.evaluate(result => Config.applyCipherResults(result, null), mixed), false,
          'A mixed result with an old cipher still requires a captured snapshot');
        assert.equal(await page.locator('#S_Server1_Cipher').inputValue(), result.Servers[0].OldCipher);
        boot.setSavedValue('Server1.Cipher', selected);
        assert.equal(await page.evaluate(({ result, snapshot }) => Config.applyCipherResults(result, snapshot),
          { result: mixed, snapshot: mixedSnapshot }), true, 'Mixed old and already-selected rows reconcile together');
        const mixedValues = await page.evaluate(() => JSON.stringify(Config.config().values));
        assert.equal(await page.evaluate(({ result, snapshot }) => Config.applyCipherResults(result, snapshot),
          { result: mixed, snapshot: mixedSnapshot }), true);
        assert.equal(await page.evaluate(() => JSON.stringify(Config.config().values)), mixedValues);

        boot.setSavedValue('Server1.Cipher', result.Servers[0].OldCipher);
        boot.setSavedValue('Server2.Cipher', selected);
        await refreshSettings();
        const conflictSnapshot = await page.evaluate(() => Config.cipherSnapshot());
        const conflictValues = await page.evaluate(() => JSON.stringify(Config.config().values));
        assert.equal(await page.evaluate(({ result, snapshot }) => Config.applyCipherResults(result, snapshot),
          { result: mixed, snapshot: conflictSnapshot }), false, 'One conflicting row rejects the entire mixed result');
        assert.equal(await page.locator('#S_Server1_Cipher').inputValue(), result.Servers[0].OldCipher,
          'The earlier ready row must not be partially applied');
        assert.equal(await page.evaluate(() => JSON.stringify(Config.config().values)), conflictValues);
        boot.setSavedValue('Server2.Cipher', other);
        await refreshSettings();
        assert.equal(await page.evaluate(({ result, snapshot }) => Config.applyCipherResults(result, snapshot),
          { result: mixed, snapshot: conflictSnapshot }), false, 'An old-cipher mutation still requires the entire captured snapshot');
        assert.equal(await page.locator('#S_Server1_Cipher').inputValue(), result.Servers[0].OldCipher);
        boot.setSavedValue('Server1.Cipher', selected);
        await refreshSettings();
        const dialog = page.locator('#TlsCipherDialog');
        // A status response can arrive after Settings was refreshed while the
        // dialog had no captured clean snapshot. Only a persisted no-op is safe.
        await page.locator('#S_Server1_Host').fill('unsaved-before-refresh.example.invalid');
        holdNextStatus = true;
        await page.locator('#Config_OptimizeTls').press('Enter');
        await dialog.waitFor({ state: 'visible' });
        await statusHeld;
        await page.locator('#TlsCipherClose').click();
        await dialog.waitFor({ state: 'hidden' });
        await refreshSettings();
        releaseStatus();
        await page.waitForFunction(() => TlsCipherDialog.canSaveSettings() &&
          document.querySelector('#TlsCipherState').textContent === 'Saved fixture cipher.');
        await page.locator('#Config_OptimizeTls').press('Enter');
        await dialog.waitFor({ state: 'visible' });
        await page.waitForFunction(() => TlsCipherDialog.canSaveSettings());
        await page.locator('#TlsCipherClose').click();
        await dialog.waitFor({ state: 'hidden' });

        // A different persisted cipher is a real conflict. Manually typing the
        // selected value must not turn an unsaved edit into a saved baseline.
        boot.setSavedValue('Server1.Cipher', other);
        await page.reload();
        await boot({ theme, width });
        await newsEditor();
        const conflictingSnapshot = await page.evaluate(() => Config.cipherSnapshot());
        assert.equal(await page.evaluate(({ result, snapshot }) => Config.applyCipherResults(result, snapshot),
          { result, snapshot: conflictingSnapshot }), false, 'An unrelated persisted cipher is not a completed result');
        await page.locator('#S_Server1_Cipher').fill(selected);
        assert.equal(await page.evaluate(({ result, snapshot }) => Config.applyCipherResults(result, snapshot),
          { result, snapshot: conflictingSnapshot }), false, 'An unsaved selected cipher must not be accepted as persisted');
        await page.locator('#S_Server1_Cipher').fill(other);
        await page.locator('#Config_OptimizeTls').press('Enter');
        await dialog.waitFor({ state: 'visible' });
        await page.waitForFunction(() => /server editor changed/.test(document.querySelector('#TlsCipherState').textContent));
        assert.equal(await page.evaluate(() => TlsCipherDialog.canSaveSettings()), false);
        await page.locator('#TlsCipherClose').click();
        await dialog.waitFor({ state: 'hidden' });

        // Refresh just Settings while retaining dialog state and its old
        // snapshot. The newly loaded selected value requires no config patch.
        boot.setSavedValue('Server1.Cipher', selected);
        await page.evaluate(() => { Config.hide(); Config.show(); Config.shown(); });
        await newsEditor();
        const refreshedValues = await page.evaluate(() => JSON.stringify(Config.config().values));
        assert.equal(await page.evaluate(({ result, snapshot }) => Config.applyCipherResults(result, snapshot),
          { result, snapshot: conflictingSnapshot }), true, 'A refreshed persisted result can reconcile an older clean snapshot');
        assert.equal(await page.evaluate(() => JSON.stringify(Config.config().values)), refreshedValues);
        await page.locator('#Config_OptimizeTls').press('Enter');
        await dialog.waitFor({ state: 'visible' });
        await page.waitForFunction(() => TlsCipherDialog.canSaveSettings());
        await page.locator('#TlsCipherClose').click();
        await dialog.waitFor({ state: 'hidden' });
        await page.locator('#ConfigNav a[href="#PATHS"]').press('Enter');
        const destination = page.locator('#S_DestDir');
        await destination.fill('./fixture/dst/after-refresh');
        const saved = page.waitForResponse(response => response.request().method() === 'POST' &&
          response.request().url().includes('/jsonrpc') && response.request().postDataJSON().method === 'saveconfig');
        await page.locator('#Config_Save:visible').click();
        assert.equal((await (await saved).json()).result, true);
        assert.equal(writes.length, 1, 'Reconciliation unlocks the ordinary save without rerunning the optimizer');
        assert(writes[0].params[0].some(option => option.Name === 'Server1.Cipher' && option.Value === selected));
        assert(writes[0].params[0].some(option => option.Name === 'DestDir' && option.Value === './fixture/dst/after-refresh'));
        assert.equal(writes[0].params[0].find(option => option.Name === '_TlsCipherBaseline').Value,
          await page.evaluate(() => Config.cipherBaseline()));
        assert.deepEqual(errors, []);
        await context.close();
      }
    }
    process.stdout.write('TLS cipher real Settings integration: ' + (process.argv.includes('--offline') ? 'eight' : 'four') + ' cases passed\n');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
