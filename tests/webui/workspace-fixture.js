// Offline example replies retain the real UI renderers and RPC boundary.
const assert = require('node:assert/strict');
const examples = require('./fixtures/workspace.json');

function fixtureURL(value) {
  const url = new URL(value);
  assert(url.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(url.hostname) && url.port,
    'Use an isolated loopback fixture, never a live daemon');
  return url;
}

async function installFixture(page, writes, options = {}) {
  const now = Math.floor(Date.now() / 1000);
  const messages = [
    { ID: 10001, Kind: 'INFO', Time: now - 120, Text: 'Example archive completed successfully.' },
    { ID: 10002, Kind: 'WARNING', Time: now - 90, Text: 'Example provider is paused for this offline preview.' },
    { ID: 10003, Kind: 'ERROR', Time: now - 60, Text: 'Example article was unavailable; a backup remains queued.' }
  ];
  await page.route(/\/jsonrpc(?:\/|$|\?)/, async route => {
    const request = route.request();
    const url = new URL(request.url());
    const rpc = request.method() === 'POST' ? request.postDataJSON() : {
      id: 1, method: url.pathname.split('/').pop(),
      params: url.searchParams.getAll('').map(value => {
        try { return JSON.parse(value); } catch { return value; }
      })
    };
    if (['editqueue', 'saveconfig', 'append', 'clearlog', 'writelog', 'resetservervolume',
      'pausedownload', 'resumedownload', 'pausepost', 'resumepost', 'pausescan', 'resumescan',
      'reload', 'shutdown', 'scan', 'testserver', 'rate'].includes(rpc.method)) {
      writes.push({ method: rpc.method, params: rpc.params });
      if (options.holdMutation) await options.holdMutation({ method: rpc.method, params: rpc.params });
      return route.fulfill({ contentType: 'application/json', json: { id: rpc.id, result: true } });
    }
    if (rpc.method === 'log') {
      return route.fulfill({ contentType: 'application/json', json: {
        id: rpc.id, result: options.empty ? [] : messages.filter(message => !rpc.params[0] || message.ID >= rpc.params[0])
      } });
    }
    if (rpc.method === 'readurl') {
      const catalog = String(rpc.params[0]).endsWith('/extensions.json');
      const result = catalog ? '[]' : JSON.stringify({ 'stable-version': '26.3', 'testing-version': '26.3' });
      return route.fulfill({ contentType: 'application/json', json: { id: rpc.id, result } });
    }
    if (['listgroups', 'history', 'servervolumes'].includes(rpc.method)) {
      const body = { id: rpc.id, result: JSON.parse(JSON.stringify(examples[rpc.method])) };
      if (options.empty && ['listgroups', 'history'].includes(rpc.method)) body.result = [];
      if (rpc.method === 'listgroups' && options.groups && !options.empty) {
        body.result = Array.from({ length: options.groups }, (_, index) => ({
          ...body.result[index % body.result.length], NZBID: 1001 + index,
          NZBName: `Example archive ${String(index + 1).padStart(2, '0')}`
        }));
      }
      if (rpc.method === 'history') {
        body.result.forEach((item, index) => {
          item.Health = index === 1 ? 800 : 1000;
          item.DeleteStatus = index === 1 ? 'HEALTH' : index === 2 ? 'DUPE' : 'NONE';
          item.Status = index === 1 ? 'FAILURE/HEALTH' : index === 2 ? 'DELETED/DUPE' : 'SUCCESS/ALL';
          item.ParStatus = index === 0 ? 'SUCCESS' : 'NONE';
          item.UnpackStatus = index === 0 ? 'SUCCESS' : 'NONE';
        });
      } else {
        if (rpc.method === 'listgroups') body.result.forEach((group, index) => {
          group.MinPostTime = now - (index + 1) * 3600;
          group.MaxPostTime = group.MinPostTime;
        });
        if (rpc.method === 'servervolumes') body.result.forEach(server => {
          server.DataTime = now;
          server.FirstDay = Math.floor(now / 86400);
          for (const key of ['BytesPerSeconds', 'BytesPerMinutes', 'BytesPerHours', 'BytesPerDays']) {
            server[key].forEach((point, index) => {
              point.SizeMB = 6 + (index % 11) * 2;
              point.SizeLo = point.SizeMB * 1048576;
              point.SizeHi = 0;
            });
          }
          server.ArticlesPerDays.forEach(point => { point.Success = 2400; point.Failed = 12; });
        });
      }
      return route.fulfill({ contentType: 'application/json', json: body });
    }
    await route.continue();
  });
}

module.exports = { fixtureURL, installFixture };
