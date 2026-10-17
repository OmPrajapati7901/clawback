// Browser regression checks. Start the frontend on :8099, backend on :8000, and Chrome with CDP on :9226.
// CDP_PORT=9226 node tests/cdp_review.mjs [/tmp/clawback-review]
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const output = process.argv[2] || '/tmp/clawback-review';
mkdirSync(output, { recursive: true });
const targets = await (await fetch(`http://127.0.0.1:${process.env.CDP_PORT || 9226}/json/list`)).json();
const target = targets.find((item) => item.type === 'page');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((done) => ws.addEventListener('open', done));
let sequence = 0;
const pending = new Map();
const exceptions = [];
const consoleErrors = [];
ws.addEventListener('message', ({ data }) => {
  const message = JSON.parse(data);
  if (message.id) {
    const callback = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) callback.reject(new Error(message.error.message));
    else callback.resolve(message.result);
  }
  if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails);
  if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') consoleErrors.push(message.params.args);
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++sequence;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
});
const evaluate = async (expression) => {
  const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result.value;
};
const pause = (ms) => new Promise((done) => setTimeout(done, ms));
const app = `Alpine.$data(document.querySelector('[x-data="clawback"]'))`;
const waitFor = async (expression, timeout = 30000) => {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await evaluate(expression)) return;
    await pause(100);
  }
  throw new Error(`Timed out: ${expression}`);
};
const navigate = async (url, width) => {
  await send('Emulation.setDeviceMetricsOverride', { width, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url });
  await waitFor(`document.readyState === 'complete' && !!window.Alpine && !${app}.loadingInvoices && !${app}.detailLoading`);
};
const shot = async (name) => {
  await pause(900);
  const screenshot = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(`${output}/${name}.png`, Buffer.from(screenshot.data, 'base64'));
};

try {
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Page.bringToFront');
  await send('Emulation.setFocusEmulationEnabled', { enabled: true });
  await navigate('http://127.0.0.1:8099/?mock=1&invoice=INV-1007&version=v2', 1680);
  await waitFor(`${app}.detail?.result && !${app}.running`);
  assert.equal(await evaluate(`${app}.detail.result.version`), 'v2');
  assert.equal(await evaluate(`${app}.stats.recovered_usd`), 4480);
  assert.equal(await evaluate(`document.querySelectorAll('tbody .strike').length`), 1, 'new findings highlight the invoice');
  assert.equal(await evaluate(`${app}.highlighted`), '3.2');
  await shot('desktop-pending-complete');

  await evaluate(`${app}.openInvoice('INV-1003')`);
  assert.equal(await evaluate(`${app}.detail.result.decision`), 'APPROVE');
  await evaluate(`${app}.openInvoice('INV-1005')`);
  assert.equal(await evaluate(`${app}.detail.result.decision`), 'FLAG');
  assert.equal(await evaluate(`document.querySelectorAll('tbody .strike').length`), 0, 'unpriced items are not struck through as overcharges');
  await evaluate(`${app}.openInvoice('INV-1007')`);
  assert.equal(await evaluate(`${app}.running`), false, 'mock results persist across navigation');
  assert.equal(await evaluate(`${app}.detail.result.version`), 'v2');
  await evaluate(`Promise.all([${app}.openInvoice('INV-1001'), ${app}.openInvoice('INV-1003')])`);
  assert.equal(await evaluate(`${app}.detail.invoice.invoice_no`), 'INV-1003');

  for (const width of [1280, 390]) {
    await navigate('http://127.0.0.1:8099/?mock=1&invoice=INV-1001', width);
    await waitFor(`${app}.contract && !${app}.contractLoading`);
    assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'), false, `${width}px has no page overflow`);
    assert.equal(await evaluate(`document.activeElement === ${app}.$refs.detailHeading`), true, 'opening a detail moves keyboard focus');
    assert.equal(await evaluate(`document.querySelector('table').getBoundingClientRect().top > 0`), true, 'highlight does not scroll past invoice');
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
    assert.match(await evaluate('document.activeElement.textContent.trim()'), /Run again/, 'tab reaches the run button');
    await shot(`detail-${width}`);
  }

  // Block the CDNs to exercise the vendored fallback, rather than requiring network at the demo.
  await send('Network.enable');
  await send('Network.setBlockedURLs', { urls: ['*cdn.tailwindcss.com*', '*cdn.jsdelivr.net*'] });
  await navigate('http://127.0.0.1:8099/?mock=1&invoice=INV-1001', 1280);
  await waitFor(`${app}.contract && getComputedStyle(document.body).backgroundColor === 'rgb(245, 247, 249)'`);
  assert.equal(await evaluate(`document.fonts.check('14px Geist')`), true);
  await shot('offline-cdn-fallback');
  await send('Network.setBlockedURLs', { urls: [] });

  await navigate('http://127.0.0.1:8099/', 1280);
  assert.match(await evaluate(`${app}.inboxError`), /Could not load the inbox/);
  assert.equal(await evaluate(`[...document.querySelectorAll('button')].some(button => button.textContent.trim() === 'Retry inbox' && button.getClientRects().length)`), true);
  await shot('backend-unavailable');

  // Upload through the actual input and backend. Only the synthetic repository invoice is used.
  await navigate('http://127.0.0.1:8000/?invoice=INV-1001', 1680);
  await send('DOM.enable');
  const { root } = await send('DOM.getDocument');
  const { nodeId } = await send('DOM.querySelector', { nodeId: root.nodeId, selector: 'input[type=file]' });
  await send('DOM.setFileInputFiles', { nodeId, files: [resolve('data/invoices/INV-1001.json')] });
  await waitFor(`${app}.uploading || ${app}.running`);
  await waitFor(`!${app}.uploading && !${app}.running && ${app}.hasLiveSteps`, 120000);
  assert.equal(await evaluate(`${app}.runError || ${app}.uploadError`), '');
  assert.equal(await evaluate(`${app}.detail.result.total_delta_usd`), 4180);
  assert.equal(await evaluate(`${app}.detail.result.version`), 'v1');
  assert.equal(await evaluate(`${app}.steps.every(s => s.status === 'ok' || s.status === 'error')`), true);
  const href = await evaluate(`${app}.mailtoHref()`);
  assert.match(href, /^mailto:\?subject=/);
  assert.match(decodeURIComponent(href), /INV-1001/);
  await send('Browser.grantPermissions', { origin: 'http://127.0.0.1:8000', permissions: ['clipboardReadWrite', 'clipboardSanitizedWrite'] });
  await evaluate(`${app}.copyEmail()`);
  assert.match(await evaluate('navigator.clipboard.readText()'), /INV-1001/);
  await shot('live-upload-v1');
  await send('Browser.resetPermissions');

  await send('DOM.setFileInputFiles', { nodeId, files: [resolve('data/invoices/INV-1001.pdf')] });
  await waitFor(`${app}.uploading || ${app}.running`);
  await waitFor(`!${app}.uploading && !${app}.running && ${app}.hasLiveSteps`, 120000);
  assert.equal(await evaluate(`${app}.runError || ${app}.uploadError`), '');
  assert.equal(await evaluate(`${app}.detail.result.total_delta_usd`), 4180);
  await shot('live-pdf-upload');
  assert.equal(exceptions.length, 0, JSON.stringify(exceptions));
  assert.equal(consoleErrors.length, 0, JSON.stringify(consoleErrors));
  console.log(`Passed: decisions, pending replay, v2 mock, stats, reactive highlights, navigation, 1280px/mobile, keyboard, offline fallback, backend unavailable, live JSON/PDF upload v1, clipboard, mailto. Screenshots: ${output}`);
} finally {
  await send('Network.setBlockedURLs', { urls: [] });
  await send('Browser.resetPermissions');
  await send('Emulation.setFocusEmulationEnabled', { enabled: false });
  ws.close();
}
