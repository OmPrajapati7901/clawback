// Drive headless Chrome over CDP: wait for a run to finish, screenshot, exercise
// closeDetail(), then report console errors/exceptions.
// usage: CDP_PORT=9223 node tests/cdp_probe.mjs <url> <out.png> [waitMs]
const [url, outPng, waitMsArg] = process.argv.slice(2);
const waitMs = Number(waitMsArg || 90000);
const port = process.env.CDP_PORT || 9222;

const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && t.url.includes('127.0.0.1:8000')) || list.find((t) => t.type === 'page');
if (!page) { console.error('no page target found', list.map((t) => t.url)); process.exit(1); }

const ws = new WebSocket(page.webSocketDebuggerUrl);
let seq = 0;
const pending = new Map();
const events = [];
ws.addEventListener('message', (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d.result); pending.delete(d.id); }
  else if (d.method) events.push(d);
});
await new Promise((r) => ws.addEventListener('open', r));
const send = (method, params = {}) => new Promise((res) => { const i = ++seq; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r?.result?.value;
};
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const appExpr = `window.Alpine && document.querySelector('[x-data="clawback"]') ? Alpine.$data(document.querySelector('[x-data="clawback"]')) : null`;

await send('Runtime.enable');
await send('Log.enable');
await send('Page.enable');
if (process.env.CDP_WIDTH) await send('Emulation.setDeviceMetricsOverride', {
  width: Number(process.env.CDP_WIDTH), height: Number(process.env.CDP_HEIGHT || 1000), deviceScaleFactor: 1, mobile: false,
});
if (url) await send('Page.navigate', { url });

const t0 = Date.now();
let state = {};
let sawRunning = false;
let ready = false;
while (Date.now() - t0 < waitMs) {
  ready = await evaluate(`(() => { const a = ${appExpr}; return !!a && !a.loadingInvoices && !a.detailLoading && (!new URLSearchParams(location.search).has('invoice') || !!a.detail); })()`);
  if (ready) break;
  await pause(100);
}
if (!ready) throw new Error('App did not become ready');
const clicks = (process.env.CDP_CLICK || '').split('|').map((s) => s.trim()).filter(Boolean);
for (const label of clicks) {
  const ok = await evaluate(`(() => { const b = [...document.querySelectorAll('button,a')].find(x => x.getClientRects().length && !x.disabled && x.textContent.trim().startsWith(${JSON.stringify(label)})); if (b) { b.click(); return true; } return false; })()`);
  console.log(`click "${label}":`, ok ? 'ok' : 'NOT FOUND');
  if (!ok) throw new Error(`Button not found: ${label}`);
  if (await evaluate(`(${appExpr})?.running`)) sawRunning = true;
  await pause(100);
}
while (Date.now() - t0 < waitMs) {
  await new Promise((r) => setTimeout(r, 1200));
  state = (await evaluate(`(() => ({
    running: (${appExpr})?.running,
    runError: (${appExpr})?.runError,
    selectedVersion: (${appExpr})?.version,
    overflow: document.documentElement.scrollWidth > innerWidth,
    steps: [...document.querySelectorAll('ol li')].map(li => li.innerText.replace(/\\n/g, ' ')),
    verdict: (document.body.innerText.match(/Overbilled [\\d,$\\.]+/) || [''])[0],
    recovered: (document.body.innerText.match(/Recovered\\s+([\\d,\\.$]+)/) || ['', ''])[1],
    version: (document.body.innerText.match(/Run (v\\d)/) || ['', ''])[1],
  }))()`)) || {};
  if (state.running) sawRunning = true;
  if (sawRunning && !state.running) break;
  if (!sawRunning && !process.env.CDP_EXPECT_RUN && !state.running && state.verdict) break;
}
await new Promise((r) => setTimeout(r, 1200)); // let the count-up settle

const shot = await send('Page.captureScreenshot', { format: 'png' });
const { writeFileSync } = await import('node:fs');
writeFileSync(outPng || '/tmp/cb-live.png', Buffer.from(shot.data, 'base64'));

// exercise the back-to-inbox path (mobile button), which nulls `detail`
await evaluate(`(() => { const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === 'Inbox'); if (b) b.click(); return !!b; })()`);
await new Promise((r) => setTimeout(r, 900));

const errors = events.filter((e) => e.method === 'Runtime.consoleAPICalled' && e.params.type === 'error')
  .map((e) => (e.params.args || []).map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300));
const exceptions = events.filter((e) => e.method === 'Runtime.exceptionThrown')
  .map((e) => `${e.params.exceptionDetails.text} ${(e.params.exceptionDetails.exception?.description || '').slice(0, 240)}`);
const logErrors = events.filter((e) => e.method === 'Log.entryAdded' && e.params.entry.level === 'error')
  .map((e) => e.params.entry.text.slice(0, 300));

console.log('--- state ---'); console.log(JSON.stringify(state, null, 1));
console.log('--- console errors ---'); console.log(JSON.stringify(errors, null, 1));
console.log('--- exceptions ---'); console.log(JSON.stringify(exceptions, null, 1));
console.log('--- log errors ---'); console.log(JSON.stringify(logErrors, null, 1));
console.log('screenshot ->', outPng);
const failed = state.running || state.runError || state.overflow || errors.length || exceptions.length || logErrors.length || (process.env.CDP_EXPECT_RUN && !sawRunning);
ws.close();
process.exit(failed ? 1 : 0);
