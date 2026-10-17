/* Clawback — Alpine component + thin API layer (live backend or ?mock=1 fixtures).
   Money math and decisions come from the backend; this file only renders them. */

const STEP_LABELS = {
  parse_invoice: 'Read the invoice',
  resolve_vendor: 'Match vendor',
  load_contract_terms: 'Read the contract',
  compute_expected: 'Price the lines',
  compare_lines: 'Compare',
  explain_findings: 'Find clauses',
  verify_citations: 'Verify quotes',
  decide_and_draft: 'Decide & draft',
  grade: 'Grade vs label',
};
const STEP_ORDER = Object.keys(STEP_LABELS);

const TYPE_LABELS = {
  ESCALATOR_EXCEEDED: 'Price raised over the cap',
  TIER_DISCOUNT_MISSED: 'Volume discount missed',
  INCLUDED_ITEM_BILLED: 'Billed for an included item',
  RATE_MISMATCH: 'Above the contract rate',
  MATH_ERROR: 'Arithmetic error',
  UNKNOWN_SKU: 'Not in the contract',
};

/* GET /api/invoices/{no} has no vendor_id and the CONTRACT shape is frozen, so the
   five synthetic vendors are mapped here. Mirrors data/vendors.json. */
const VENDORS = [
  ['corvina_freight', ['Corvina Freight Systems LLC', 'Corvina Freight', 'Corvina Freight Systems']],
  ['heliotrope_cloud', ['Heliotrope Cloud Hosting, Inc.', 'Heliotrope Cloud', 'Heliotrope Hosting']],
  ['brightloom_facilities', ['Brightloom Facilities Services', 'Brightloom Facilities', 'Brightloom Services']],
  ['pinecrest_supply', ['Pinecrest Office Supply Company', 'Pinecrest Supply', 'Pinecrest Office']],
  ['kestrel_staffing', ['Kestrel Staffing Partners', 'Kestrel Staffing']],
];

const normName = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const VENDOR_IDS = {};
for (const [id, names] of VENDORS) for (const n of names) VENDOR_IDS[normName(n)] = id;

const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const MIN_STEP_MS = 280;      // readability floor for step transitions (ms labels stay truthful)
const MOCK_SPEED = 0.4;       // mock replay: scale real/canned ms
const MOCK_MIN_MS = 380;
const MOCK_MAX_MS = 3000;

function clawback() {
  return {
    // ── state ──────────────────────────────────────────────────────────────
    mock: new URLSearchParams(location.search).get('mock') === '1',
    version: new URLSearchParams(location.search).get('version') === 'v2' ? 'v2' : 'v1',
    invoices: [],
    loadingInvoices: true,
    inboxError: '',
    stats: { recovered_usd: 0, invoices: 0, disputes: 0, flags: 0, approvals: 0 },
    shownRecovered: 0,

    selectedNo: null,
    detail: null,
    detailLoading: false,

    steps: [],
    hasLiveSteps: false,
    running: false,
    runError: '',
    liveDetail: '',
    liveMs: '',

    contract: null,
    contractLoading: false,
    contractError: '',
    highlighted: '',

    uploading: false,
    uploadError: '',
    dragOver: false,
    toastMsg: '',
    emailCopied: false,

    _es: null,
    _tick: null,
    _queue: null,
    _runId: 0,
    _statsLoaded: false,
    _toastTimer: null,
    _emailTimer: null,
    _viewId: 0,
    _contractId: 0,
    _recoveredFrame: null,
    _mockResults: {},

    // ── boot ───────────────────────────────────────────────────────────────
    async init() {
      document.getElementById('boot')?.remove();
      const q = new URLSearchParams(location.search);
      const first = q.get('invoice');
      await Promise.all([this.loadInvoices(), this.loadStats()]);
      if (first) this.openInvoice(first);
    },

    get topStats() {
      return [
        { key: 'invoices', label: 'Invoices', value: this.stats.invoices ?? 0 },
        { key: 'disputes', label: 'Disputes', value: this.stats.disputes ?? 0 },
        { key: 'flags', label: 'Flags', value: this.stats.flags ?? 0 },
        { key: 'approvals', label: 'Approvals', value: this.stats.approvals ?? 0 },
      ];
    },

    // ── api (live or mock) ─────────────────────────────────────────────────
    async api(path, opts = {}) {
      if (this.mock) return this.mockApi(path, opts);
      const res = await fetch(path, opts);
      if (!res.ok) {
        let msg = `request failed (${res.status})`;
        try { const j = await res.json(); if (j.detail) msg = j.detail; } catch {}
        throw new Error(msg);
      }
      return res.json();
    },

    async mockApi(path) {
      const file = (name) => fetch(`mock/${name}`).then((r) => {
        if (!r.ok) throw new Error(`fixture ${name} missing`);
        return r.json();
      });
      let m;
      if (path === '/api/stats') return file('stats.json');
      if (path === '/api/invoices') return file('invoices.json');
      if ((m = path.match(/^\/api\/invoices\/([^/]+)$/))) {
        const detail = await file(`invoice-${m[1]}.json`);
        if (this._mockResults[m[1]]) detail.result = this._mockResults[m[1]];
        return detail;
      }
      if ((m = path.match(/^\/api\/contracts\/([^/]+)$/))) return file(`contract-${m[1]}.json`);
      throw new Error(`no mock fixture for ${path}`);
    },

    async loadInvoices() {
      this.inboxError = '';
      try {
        this.invoices = await this.api('/api/invoices');
      } catch (e) {
        this.inboxError = `Could not load the inbox: ${e.message}`;
      } finally {
        this.loadingInvoices = false;
      }
    },

    async loadStats() {
      try {
        if (this.mock) {
          if (!this._statsLoaded) { this.stats = await this.api('/api/stats'); this._statsLoaded = true; }
          else this.stats = this.statsFromRows();
        } else {
          this.stats = await this.api('/api/stats');
        }
      } catch {}
      this.animateRecovered();
    },

    statsFromRows() {
      const s = { recovered_usd: 0, invoices: this.invoices.length, disputes: 0, flags: 0, approvals: 0 };
      for (const r of this.invoices) {
        if (r.decision === 'DISPUTE') { s.disputes += 1; s.recovered_usd += r.total_delta_usd || 0; }
        else if (r.decision === 'FLAG') s.flags += 1;
        else if (r.decision === 'APPROVE') s.approvals += 1;
      }
      s.recovered_usd = Math.round(s.recovered_usd * 100) / 100;
      return s;
    },

    animateRecovered() {
      cancelAnimationFrame(this._recoveredFrame);
      const target = Number(this.stats.recovered_usd) || 0;
      if (REDUCED) { this.shownRecovered = target; return; }
      const from = this.shownRecovered;
      if (from === target) return;
      const t0 = performance.now(), dur = 800;
      const tick = (now) => {
        const p = Math.max(0, Math.min(1, (now - t0) / dur));
        const eased = 1 - Math.pow(1 - p, 3);
        this.shownRecovered = from + (target - from) * eased;
        if (p < 1) this._recoveredFrame = requestAnimationFrame(tick);
        else this.shownRecovered = target;
      };
      this._recoveredFrame = requestAnimationFrame(tick);
    },

    // ── invoice detail ─────────────────────────────────────────────────────
    async openInvoice(no, forceRun = false) {
      const viewId = ++this._viewId;
      this._contractId += 1;
      this.cancelRun();
      this.selectedNo = no;
      this.detail = null;
      this.detailLoading = true;
      this.resetRun();
      this.contract = null;
      this.contractLoading = false;
      this.contractError = '';
      this.highlighted = '';
      this.uploadError = '';
      try {
        const d = await this.api(`/api/invoices/${encodeURIComponent(no)}`);
        if (viewId !== this._viewId) return;
        this.detail = d;
        this.loadContract(d.invoice);
        if (forceRun || !d.result) this.runInvoice(no);
        this.$nextTick(() => this.$refs.detailHeading?.focus({ preventScroll: true }));
      } catch (e) {
        if (viewId !== this._viewId) return;
        this.selectedNo = null;
        this.toast(`Could not open ${no}: ${e.message}`);
      } finally {
        if (viewId === this._viewId) this.detailLoading = false;
      }
    },

    closeDetail() {
      this._viewId += 1;
      this._contractId += 1;
      this.cancelRun();
      this.selectedNo = null;
      this.detail = null;
      this.detailLoading = false;
      this.contractLoading = false;
      this.resetRun();
      this.contract = null;
      this.highlighted = '';
      this.$nextTick(() => this.$refs.inboxHeading?.focus({ preventScroll: true }));
    },

    async loadContract(invoice) {
      if (!invoice) return;
      const contractId = ++this._contractId;
      const vid = VENDOR_IDS[normName(invoice.vendor_name_raw)];
      if (!vid) {
        this.contractLoading = false;
        this.contract = null;
        this.contractError = `No contract is on file for “${invoice.vendor_name_raw}”.`;
        return;
      }
      this.contractLoading = true;
      this.contractError = '';
      try {
        const contract = await this.api(`/api/contracts/${vid}`);
        if (contractId !== this._contractId) return;
        this.contract = contract;
        const first = this.detail?.result?.findings.find((f) => f.clause_id);
        if (first) this.clauseJump(first.clause_id, false);
      } catch (e) {
        if (contractId !== this._contractId) return;
        this.contract = null;
        this.contractError = `Could not load the contract: ${e.message}`;
      } finally {
        if (contractId === this._contractId) this.contractLoading = false;
      }
    },

    // ── the run ────────────────────────────────────────────────────────────
    resetRun() {
      this.steps = STEP_ORDER.map((name) => ({ name, status: 'pending', detail: '', ms: 0 }));
      this.hasLiveSteps = false;
      this.running = false;
      this.runError = '';
      this.liveDetail = '';
      this.liveMs = '';
      clearInterval(this._tick);
      this._queue = null;
      this._lastApply = 0;
    },

    cancelRun() {
      this._runId += 1;
      if (this._es) { this._es.close(); this._es = null; }
      clearInterval(this._tick);
      this.running = false;
    },

    runInvoice(no) {
      if (this.running || !no) return;
      this.resetRun();
      const runId = ++this._runId;
      this._runVersion = this.version;
      this.hasLiveSteps = true;
      this.running = true;
      this._stepStartedAt = performance.now();
      this._tick = setInterval(() => {
        if (!this.running || !this._stepStartedAt) return;
        const t = performance.now() - this._stepStartedAt;
        this.liveMs = t < 1000 ? `${Math.round(t)} ms` : `${(t / 1000).toFixed(1)} s`;
      }, 100);
      if (this.mock) this.replayRun(no, runId);
      else this.streamRun(no, runId);
    },

    streamRun(no, runId) {
      const es = new EventSource(`/api/invoices/${encodeURIComponent(no)}/process?version=${this.version}`);
      this._es = es;
      es.onmessage = (m) => {
        if (runId !== this._runId) return;
        let ev;
        try { ev = JSON.parse(m.data); } catch {
          es.close();
          this.enqueueEnd(runId, 'The agent sent an unreadable event. Use “Run again” to retry.');
          return;
        }
        // Stop reconnects as soon as the terminal event arrives, before playback drains.
        if (ev.step === 'result') {
          es.close();
          if (this._es === es) this._es = null;
        }
        this.enqueue(ev, runId);
      };
      es.onerror = () => {
        es.close();
        if (this._es === es) this._es = null;
        this.enqueueEnd(runId, 'Lost the connection to the agent stream. Use “Run again” to retry.');
      };
    },

    enqueueEnd(runId, message) {
      this._queue = (this._queue || Promise.resolve()).then(() => {
        if (runId !== this._runId || !this.running) return;
        this.finishRun(null);
        this.runError = message;
      });
    },

    async replayRun(no, runId) {
      let events;
      try {
        const response = await fetch(`mock/run-${encodeURIComponent(no)}.json`);
        if (!response.ok) throw new Error('Missing replay');
        events = await response.json();
      } catch {
        if (runId !== this._runId) return;
        this.finishRun(null);
        this.runError = `No mock run fixture for ${no}.`;
        return;
      }
      for (const ev of events) {
        if (runId !== this._runId) return;
        if (ev.status === 'running') { this.applyStep(ev); continue; }
        if (ev.step === 'result') { this.finishRun({ ...ev.result, version: this._runVersion }); return; }
        const wait = REDUCED ? 30 : Math.max(MOCK_MIN_MS, Math.min(MOCK_MAX_MS, ev.ms * MOCK_SPEED));
        await sleep(wait);
        if (runId !== this._runId) return;
        this.applyStep(ev);
      }
      this.finishRun(null);
    },

    // step events are queued so a fast stream still reads as a sequence
    enqueue(ev, runId = this._runId) {
      this._queue = (this._queue || Promise.resolve()).then(async () => {
        if (runId !== this._runId) return;
        if (ev.step === 'result') { this.finishRun(ev.result); return; }
        const now = performance.now();
        if (this._lastApply && !REDUCED) {
          const wait = this._lastApply + MIN_STEP_MS - now;
          if (wait > 0) await sleep(wait);
        }
        if (runId !== this._runId) return;
        this._lastApply = performance.now();
        this.applyStep(ev);
      });
    },

    applyStep(ev) {
      let s = this.steps.find((x) => x.name === ev.step);
      if (!s) { s = { name: ev.step, status: 'pending', detail: '', ms: 0 }; this.steps.push(s); }
      s.status = ev.status;
      s.ms = ev.ms || 0;
      if (ev.detail) s.detail = ev.detail;
      if (ev.status === 'running') {
        this._stepStartedAt = performance.now();
        this.liveMs = '';
      } else if (ev.detail) {
        this.liveDetail = ev.detail;
      }
    },

    finishRun(result) {
      this.running = false;
      this.liveMs = '';
      clearInterval(this._tick);
      for (const step of this.steps) {
        if (step.status === 'pending') step.status = 'skipped';
        if (step.status === 'running') {
          step.status = result ? 'skipped' : 'error';
          step.detail = 'The stream ended before this step completed.';
        }
      }
      if (this._es) { this._es.close(); this._es = null; }
      if (!result) {
        this.runError = 'The run ended without a result.';
        return;
      }
      this.detail = { ...(this.detail || {}), result };
      if (this.mock) this._mockResults[result.invoice_no] = result;
      this.touchRow(result);
      this.loadStats();
      const first = (result.findings || []).find((f) => f.clause_id);
      if (first) this.clauseJump(first.clause_id, false);
      if (result.run_status === 'failed') this.toast('Audit finished with warnings — check the steps.');
      else this.toast(this.verdictTitle());
    },

    touchRow(result) {
      const row = this.invoices.find((r) => r.invoice_no === result.invoice_no);
      if (row) {
        row.decision = result.decision;
        row.total_delta_usd = result.total_delta_usd;
        row.status = result.run_status;
      }
    },

    // ── rendering helpers ──────────────────────────────────────────────────
    money(n) {
      if (n === null || n === undefined || Number.isNaN(Number(n))) return '—';
      const v = Number(n);
      const sign = v < 0 ? '-' : '';
      return sign + '$' + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },

    stepLabel(name) { return STEP_LABELS[name] || name; },
    typeLabel(type) { return TYPE_LABELS[type] || type; },

    resultMeta() {
      const r = this.detail?.result;
      if (!r) return '';
      const n = r.findings.length;
      return `Run ${r.version} · ${n === 0 ? 'no findings' : n + (n === 1 ? ' finding' : ' findings')}`;
    },

    lastRunText() {
      return this.detail?.result ? `last run ${this.detail.result.version}` : '';
    },

    stepItemClass(s) {
      if (s.status === 'running') return 'border-ink/25 bg-paper text-ink shadow-panel';
      if (s.status === 'ok') return 'border-hairline bg-surface text-ink';
      if (s.status === 'error') return 'border-red-ink/30 bg-red-wash text-red-ink';
      return 'border-hairline bg-surface text-ink-faint';
    },

    totalMsText() {
      const ms = this.steps.reduce((a, s) => a + (s.ms || 0), 0);
      return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s total` : `${ms} ms total`;
    },

    chipClass(d) {
      if (d === 'DISPUTE') return 'border-red-ink/25 bg-red-wash text-red-ink';
      if (d === 'FLAG') return 'border-ochre-ink/25 bg-ochre-wash text-ochre-ink';
      if (d === 'APPROVE') return 'border-green-ink/25 bg-green-wash text-green-ink';
      return 'border-hairline bg-paper text-ink-muted';
    },
    chipLabel(d) {
      return { DISPUTE: 'Dispute', FLAG: 'Flag', APPROVE: 'Approve' }[d] || 'Pending';
    },
    stampLabel(d) { return { DISPUTE: 'Dispute', FLAG: 'Flag', APPROVE: 'Approved' }[d] || ''; },
    stampClass(d) {
      if (d === 'DISPUTE') return 'text-red-ink';
      if (d === 'FLAG') return 'text-ochre-ink';
      if (d === 'APPROVE') return 'text-green-ink';
      return 'text-ink-faint';
    },
    rowDelta(row) {
      if (!row.decision) {
        return (this.running && this.selectedNo === row.invoice_no) ? 'Auditing…' : 'Not run yet';
      }
      if (row.total_delta_usd > 0) return `+${this.money(row.total_delta_usd)}`;
      return row.decision === 'FLAG' ? 'no claim' : this.money(0);
    },
    rowDeltaClass(row) {
      return row.total_delta_usd > 0 ? 'text-red-ink' : 'text-ink-faint';
    },

    findingFor(sku) {
      return (this.detail?.result?.findings || []).find((f) => f.sku === sku);
    },

    lineNote(li) {
      const f = this.findingFor(li.sku);
      if (!f) return '';
      if (f.type === 'UNKNOWN_SKU') return 'This SKU is not in the contract, so it cannot be priced.';
      if (f.type === 'INCLUDED_ITEM_BILLED') return `Included in the contract at no charge, so ${this.money(0)} is allowed (clause ${f.clause_id}).`;
      if (f.type === 'MATH_ERROR') return `Correct amount for this line is ${this.money(f.expected_amount)} (clause ${f.clause_id}).`;
      return `Contract allows ${this.money(f.expected_amount)}, per clause ${f.clause_id}.`;
    },

    totalNote() {
      const f = (this.detail?.result?.findings || []).find((x) => x.type === 'MATH_ERROR' && x.sku === 'TOTAL');
      return f ? `The line amounts do not add up to the invoice total. Correct total is ${this.money(f.expected_amount)}.` : '';
    },

    verdictTitle() {
      const r = this.detail?.result;
      if (!r) return '';
      if (r.run_status === 'failed' && !r.findings.length) return 'Audit needs attention';
      if (r.decision === 'DISPUTE') return `Overbilled ${this.money(r.total_delta_usd)}`;
      if (r.decision === 'FLAG') {
        return r.total_delta_usd > 0 ? `Needs review: ${this.money(r.total_delta_usd)}` : 'Needs review: line not in contract';
      }
      return 'No overcharges found';
    },

    verdictSub() {
      const r = this.detail?.result;
      if (!r) return '';
      if (r.run_status === 'failed') return 'The audit reported a problem. Review the steps and citation checks before following up.';
      const n = r.findings.length;
      if (r.decision === 'DISPUTE') {
        return n === 1 ? 'One line breaches the contract. A dispute email is ready below.'
                       : `${n} lines breach the contract. A dispute email is ready below.`;
      }
      if (r.decision === 'FLAG') {
        return r.total_delta_usd > 0
          ? 'At or below the $250 dispute threshold, so no email was drafted. Review the cited clause below.'
          : 'No contract price for this line, so no dollar claim was made.';
      }
      return 'Every line was checked against the contract.';
    },

    noEmailReason() {
      const r = this.detail?.result;
      if (!r) return '';
      if (r.run_status === 'failed') return 'This audit could not produce an email. Review the steps and run it again.';
      if (r.decision === 'APPROVE') return 'No overcharges were found, so there is nothing to dispute.';
      if (r.total_delta_usd > 0) return 'The overcharge is at or below the $250 dispute threshold, so no email was drafted.';
      return 'There is no dollar amount to claim, so no email was drafted.';
    },

    traceText() {
      const id = this.detail?.result?.trace_id;
      return id ? `PRISM trace ${String(id).slice(0, 8)}` : '';
    },

    citedClauses() {
      const out = [];
      for (const f of this.detail?.result?.findings || []) {
        if (f.clause_id && !out.includes(f.clause_id)) out.push(f.clause_id);
      }
      return out;
    },

    isCited(cid) { return this.citedClauses().includes(cid); },

    clauseTitle(cid) {
      const c = (this.contract?.terms?.clauses || []).find((x) => x.id === cid);
      return c ? c.title : '';
    },

    clauseJump(cid, reveal = true) {
      if (!cid) return;
      this.highlighted = '';
      this.$nextTick(() => {
        this.highlighted = cid;
        const box = this.$refs.contractScroll;
        if (!box) return;
        const el = box.querySelector(`[id="clause-${cid}"]`);
        if (!el) return;
        const top = Math.max(0, el.offsetTop - 14);
        box.scrollTo({ top, behavior: REDUCED ? 'auto' : 'smooth' });
        const r = box.getBoundingClientRect();
        if (reveal && (r.top < 0 || r.bottom > window.innerHeight)) box.scrollIntoView({ block: 'nearest', behavior: REDUCED ? 'auto' : 'smooth' });
      });
    },

    contractMeta() {
      const t = this.contract?.terms;
      if (!t) return '';
      const bits = [];
      bits.push(`effective ${t.effective_date}`);
      if (t.escalator_max_pct) bits.push(`max ${(t.escalator_max_pct * 100).toFixed(1)}% a year`);
      bits.push(`${t.clauses.length} clauses`);
      return bits.join(' · ');
    },

    setVersion(v) {
      this.version = v;
      const q = new URLSearchParams(location.search);
      if (v === 'v1') q.delete('version'); else q.set('version', v);
      history.replaceState(null, '', `?${q.toString()}`);
      this.toast(`Pipeline ${v} applies to the next run`);
    },

    // ── clipboard + mail ───────────────────────────────────────────────────
    async copyEmail() {
      const e = this.detail?.result?.dispute_email;
      if (!e) return;
      try {
        await navigator.clipboard.writeText(`${e.subject}\n\n${e.body}`);
        this.emailCopied = true;
        clearTimeout(this._emailTimer);
        this._emailTimer = setTimeout(() => { this.emailCopied = false; }, 1800);
        this.toast('Dispute email copied');
      } catch {
        this.toast('The browser blocked the clipboard');
      }
    },

    async copyTrace() {
      const id = this.detail?.result?.trace_id;
      if (!id) return;
      try {
        await navigator.clipboard.writeText(id);
        this.toast('Trace id copied');
      } catch {
        this.toast('The browser blocked the clipboard');
      }
    },

    mailtoHref() {
      const e = this.detail?.result?.dispute_email;
      if (!e) return '#';
      return `mailto:?subject=${encodeURIComponent(e.subject)}&body=${encodeURIComponent(e.body)}`;
    },

    // ── upload ─────────────────────────────────────────────────────────────
    onPick(event) {
      const f = event.target.files?.[0];
      event.target.value = '';
      if (f) this.upload(f);
    },

    onDrop(event) {
      this.dragOver = false;
      const f = event.dataTransfer?.files?.[0];
      if (f) this.upload(f);
    },

    async upload(file) {
      if (this.uploading) return;
      this.uploadError = '';
      if (!/\.(pdf|json)$/i.test(file.name)) {
        this.uploadError = 'Choose a .pdf or .json invoice.';
        return;
      }
      if (this.mock) {
        this.toast(`Mock upload: ${file.name}`);
        await sleep(250);
        this.openInvoice('INV-1001', true);
        return;
      }
      this.uploading = true;
      try {
        const fd = new FormData();
        fd.append('file', file);
        const out = await this.api('/api/invoices', { method: 'POST', body: fd });
        await this.loadInvoices();
        this.toast(`${out.invoice_no} uploaded`);
        await this.openInvoice(out.invoice_no, true);
        this.loadStats();
      } catch (e) {
        this.uploadError = e.message;
        this.toast('Upload failed');
      } finally {
        this.uploading = false;
      }
    },

    toast(msg) {
      this.toastMsg = msg;
      clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => { this.toastMsg = ''; }, 2800);
    },
  };
}
