# Clawback

Audit a synthetic supplier invoice against its contract, watch the agent steps,
inspect the cited clause, and copy a drafted dispute email. CONTRACT.md defines
the data formats, pricing rules, and HTTP API.

All companies, contracts, and invoices in this repository are fictional. Use only
synthetic invoices. Synthetic data. Not legal or financial advice.

## Run the app

From the repository root, with Python 3.11+:

```sh
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cp .env.example .env
```

Fill in the Nicrron and PRISM credentials in `.env`. The existing backend routes
model calls through Nicrron and traces pipeline steps to PRISM. Keep `.env` private.
Start the server:

```sh
backend/.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>. Upload a synthetic JSON or PDF invoice from
`data/invoices/`, or select one from the inbox. A new invoice starts automatically.
Uploading an already audited invoice starts a fresh audit too. **Run again** uses
the version selected in the footer. The toggle applies to the next run.

The backend creates a local database and an uploads directory at runtime. A live
run can make model calls; do not use live mode for an offline rehearsal.

## Mock demo, without the backend

```sh
python3 -m http.server 8099 --bind 127.0.0.1 --directory frontend
```

Open <http://127.0.0.1:8099/?mock=1>. The four fixtures cover dispute, flag,
approval, and a pending invoice whose steps replay with timers. Try
<http://127.0.0.1:8099/?mock=1&invoice=INV-1007&version=v2> for an automatic replay.

Mock uploads replay INV-1001; they do not parse the selected file. Mock results
persist while navigating in the current page and reset on reload. Mock v2 changes
the run label; it uses the same synthetic replay, without calling a model. Fixture
timings and traces are demonstration data, not a fresh PRISM run.

## Frontend

`frontend/index.html`, `app.js`, and `styles.css` run directly without a build.
Tailwind 3.4.17 and Alpine 3.14.9 load from pinned CDN URLs, with vendored fallbacks;
Geist fonts are local. Serve over HTTP rather than opening `index.html` as a file.
The plain HTML components retain the Alpine/Tailwind architecture; this app does
not include the React-based shadcn/ui component runtime.

Supported URL parameters: `mock=1`, `invoice=INV-1001`, and `version=v2`.
Live pricing, findings, decisions, and email content come from the backend. The
frontend only renders them. “Recovered” displays the API's aggregate overbilling
amount, rather than tracking issued credit notes or collected cash.

## Verify

The asynchronous frontend regression tests require Node 22+ and no packages:

```sh
node --test tests/frontend_state.test.mjs
```

For browser checks, start the mock server and live backend, then launch an isolated
headless Chrome profile with `--remote-debugging-port=9226`. On macOS:

```sh
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --remote-debugging-port=9226 \
  --user-data-dir=/tmp/clawback-review-chrome --no-first-run about:blank
CDP_PORT=9226 node tests/cdp_review.mjs /tmp/clawback-review
```

This checks decisions, replay, navigation, row highlights, keyboard focus,
1280px/mobile layouts, CDN fallbacks, backend-unavailable recovery, clipboard,
mailto, and **live synthetic JSON/PDF uploads**. It writes screenshots to the
output directory and may spend model calls.
The narrower probe can verify a rerun and exits nonzero for stream/UI failures:

```sh
CDP_PORT=9226 CDP_WIDTH=1280 CDP_EXPECT_RUN=1 CDP_CLICK='v2|Run again' \
  node tests/cdp_probe.mjs 'http://127.0.0.1:8000/?invoice=INV-1004' \
  /tmp/clawback-v2.png 120000
```

Rebuild ground-truth fixtures with `python3 tests/build_mock.py`. It preserves an
existing INV-1001 capture. `tests/capture_mock.py` invokes the real traced backend,
persists a run, and can replace rejected quotes with ground-truth quotes for the
mock fixture; its output is a curated demo, not an unmodified live recording.

## Known backend issue

Some live model responses combine separated contract sentences into a quote that
fails verbatim verification. The frontend shows “Quote not found in contract” and
the failed-run warning when the API reports this. Backend code is owned separately
and was not changed in this frontend review. Review the finding before using a
draft email from a failed audit.
