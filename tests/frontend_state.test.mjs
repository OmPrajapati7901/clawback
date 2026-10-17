// No dependencies or model calls: exercise asynchronous state transitions against the real component.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../frontend/app.js', import.meta.url), 'utf8');
const fixture = JSON.parse(readFileSync(new URL('../frontend/mock/invoice-INV-1001.json', import.meta.url)));
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function component(reduced = true) {
  const streams = [];
  class EventSource {
    constructor(url) { this.url = url; streams.push(this); }
    close() { this.closed = true; }
    emit(event) { this.onmessage({ data: JSON.stringify(event) }); }
  }
  const context = vm.createContext({
    window: { matchMedia: () => ({ matches: reduced }) },
    location: { search: '' }, URLSearchParams, performance,
    setTimeout, clearTimeout, setInterval, clearInterval, EventSource,
    requestAnimationFrame: () => 1, cancelAnimationFrame() {},
  });
  const app = vm.runInContext(`${source}\nclawback()`, context);
  app.$nextTick = (fn) => fn();
  app.$refs = {};
  app.toast = () => {};
  app.loadStats = async () => {};
  app.detail = structuredClone(fixture);
  app.selectedNo = fixture.invoice.invoice_no;
  return { app, streams, context };
}

test('fast stream closes on result and drains before handling EOF', async () => {
  const { app, streams } = component(false);
  app.version = 'v2';
  app.runInvoice('INV-1001');
  const stream = streams[0];
  assert.match(stream.url, /version=v2$/);
  stream.emit({ step: 'parse_invoice', status: 'running' });
  stream.emit({ step: 'parse_invoice', status: 'ok', ms: 17 });
  stream.emit({ step: 'result', result: { ...fixture.result, version: 'v2' } });
  assert.equal(stream.closed, true);
  stream.onerror(); // The connection can close while presentation is still queued.
  await app._queue;
  assert.equal(app.running, false);
  assert.equal(app.runError, '');
  assert.equal(app.detail.result.version, 'v2');
  assert.equal(app.steps[0].status, 'ok');
  assert.equal(app.steps[0].ms, 17);
});

test('cancelling during playback prevents queued events from changing another invoice', async () => {
  const { app, streams } = component(false);
  app.runInvoice('INV-1001');
  streams[0].emit({ step: 'parse_invoice', status: 'running' });
  streams[0].emit({ step: 'parse_invoice', status: 'ok', ms: 17 });
  streams[0].emit({ step: 'result', result: fixture.result });
  const oldQueue = app._queue;
  await delay(20);
  app.closeDetail();
  app.detail = { invoice: { invoice_no: 'INV-1003' }, result: null };
  await oldQueue;
  assert.equal(app.detail.result, null);
  assert.equal(app.steps[0].status, 'pending');
});

test('a truncated stream keeps completed steps and offers a retry', async () => {
  const { app, streams } = component();
  app.runInvoice('INV-1001');
  streams[0].emit({ step: 'parse_invoice', status: 'ok', ms: 12 });
  streams[0].onerror();
  await app._queue;
  assert.equal(app.running, false);
  assert.match(app.runError, /Lost the connection/);
  assert.equal(app.steps[0].status, 'ok');
  assert.equal(app.steps[1].status, 'skipped');
});

test('late invoice responses cannot replace the current selection', async () => {
  const { app } = component();
  let resolveFirst;
  app.api = (path) => path.endsWith('INV-1001')
    ? new Promise((resolve) => { resolveFirst = resolve; })
    : Promise.resolve({ invoice: { invoice_no: 'INV-1003' }, result: fixture.result });
  app.loadContract = () => {};
  const first = app.openInvoice('INV-1001');
  await app.openInvoice('INV-1003');
  resolveFirst(fixture);
  await first;
  assert.equal(app.detail.invoice.invoice_no, 'INV-1003');
  assert.equal(app.selectedNo, 'INV-1003');
});

test('late contract responses cannot replace the current vendor contract', async () => {
  const { app } = component();
  app.detail.result = null;
  let resolveFirst;
  app.api = (path) => path.endsWith('corvina_freight')
    ? new Promise((resolve) => { resolveFirst = resolve; })
    : Promise.resolve({ text: 'Heliotrope', terms: { clauses: [] } });
  const first = app.loadContract({ vendor_name_raw: 'Corvina Freight' });
  await app.loadContract({ vendor_name_raw: 'Heliotrope Cloud' });
  resolveFirst({ text: 'Corvina', terms: { clauses: [] } });
  await first;
  assert.equal(app.contract.text, 'Heliotrope');
});

test('uploading a previously audited invoice explicitly starts a fresh run', async () => {
  const { app } = component();
  app.mock = true;
  let opened;
  app.openInvoice = (...args) => { opened = args; };
  await app.upload({ name: 'INV-1001.json' });
  assert.equal(opened[0], 'INV-1001');
  assert.equal(opened[1], true);
});

test('malformed stream events stop the run with a retry message', async () => {
  const { app, streams } = component();
  app.runInvoice('INV-1001');
  streams[0].onmessage({ data: 'not json' });
  await app._queue;
  assert.equal(streams[0].closed, true);
  assert.equal(app.running, false);
  assert.match(app.runError, /unreadable event/);
});

test('mock replay labels the result with the version captured at start', async () => {
  const { app, context } = component();
  app.mock = true;
  app.version = 'v2';
  context.fetch = async () => ({ ok: true, json: async () => [
    { step: 'parse_invoice', status: 'ok', ms: 1 },
    { step: 'result', result: fixture.result },
  ] });
  app.runInvoice('INV-1001');
  app.version = 'v1';
  await delay(60);
  assert.equal(app.detail.result.version, 'v2');
  assert.equal(app._mockResults['INV-1001'].version, 'v2');
  assert.equal(app.running, false);
});

test('missing mock fixture stops its timer and reports a clear error', async () => {
  const { app, context } = component();
  app.mock = true;
  context.fetch = async () => ({ ok: false });
  app.runInvoice('INV-1001');
  await delay(0);
  assert.equal(app.running, false);
  assert.match(app.runError, /No mock run fixture/);
});
