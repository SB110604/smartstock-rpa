# PROGRESS — SmartStock RPA

Phases follow `docs/PROJECT_SPEC.md` section 15. A phase is done only when its acceptance checks pass.
Legend: `[x]` done · `[ ]` not done · `[~]` done but verification pending (reason given).

## Phase 0 — Scaffold
Acceptance: `docker compose up --build` starts all containers healthy; `/api/v1/health` OK; frontend loads; `make test` runs.

- [x] git repo, `.gitattributes` (LF), `.gitignore`, `.editorconfig`, docs/PROGRESS.md, docs/DECISIONS.md
- [x] `docker-compose.yml` with db, redis, api, worker, beat, web, mailpit + healthchecks; `docker/db-init.sql` creates the test DB
- [x] Backend: requirements, Dockerfile (tesseract + poppler), pyproject (ruff/pytest/coverage), app factory, config, JSON logging, `{detail, code}` error format
- [x] DB session/base with naming convention + timestamp mixin; Alembic env + template
- [x] `/api/v1/health` (db, redis, worker, beat) + `/health/live`; container healthcheck module
- [x] Celery app + beat schedule with heartbeat task
- [x] Frontend: Vite + React 18 + TS strict, Tailwind (dark mode), React Router, TanStack Query, i18next (en/hi/mr), UI kit, layout shell, System status page, PWA manifest + icons
- [x] ESLint + Prettier + Vitest; multi-stage Dockerfile (test / build / nginx web) with `/api` proxy
- [x] Makefile (`up down migrate seed test e2e eval lint`), `.env.example`, `scripts/dev-db.sh` for non-Docker dev
- [x] Verified locally: backend pytest + ruff, frontend lint + vitest + build, API + worker + beat against Postgres 16 / Redis → health all `ok`
- [~] `docker compose up --build` healthy — **not run: Docker is not installed on the build machine.** Compose file, Dockerfiles and healthchecks are written; run `make up` on a machine with Docker Desktop to confirm.

## Phase 1 — Core data & auth
Acceptance: tests for auth, permissions, FEFO, import validation pass; can create products, receive stock, sell by scanning, see stock update.

- [x] All 49 tables as SQLAlchemy models + Alembic `0001_initial_schema` (upgrade/downgrade round-trip, `alembic check` clean)
- [x] Auth: bcrypt, JWT access + refresh (token_version revocation), login rate limit (Redis, memory fallback), TOTP 2FA for admin, forgot/reset password by email, change password
- [x] Central permission matrix (`app/core/permissions.py`) enforced per route via `require(...)`
- [x] Audit helper (create/update/delete/transition diffs + IP) used by every service write
- [x] Settings service with validated defaults; public settings + feature flags; POS API keys (hashed)
- [x] Users, locations, categories, products (stock status, detail), suppliers (+ price list) CRUD APIs
- [x] Stock ledger: receive (batch merge, perishable auto-expiry), FEFO issue, adjustments (reason), write-off, markdown, movements, batch expiry buckets, scan lookup (barcode / SKU / `SKU|BATCH`)
- [x] Sales with FEFO + markdown + GST back-out; POS sales API (`X-API-Key`, idempotent invoice no)
- [x] Stock counts with variance report + posting; transfers via `app/workflow/` state machine (history + audit)
- [x] Import center: products, suppliers, supplier prices, opening stock, sales history — auto-map, preview, commit, error CSV, CSV/XLSX templates
- [x] Barcode label sheets (Code128 + QR, A4 3×8) for products and batches
- [x] Frontend: login (+2FA), forgot/reset, role-filtered layout, Products (list/form/detail), Suppliers (list/form/detail/prices), Stock (in/out/adjust/transfers/counts/movements), Sales billing + history, Import center, Labels, Settings, Audit log (diff view), Profile (2FA setup), System status; html5-qrcode scanner with manual/USB-scanner fallback
- [x] Tests: backend 87 passed (auth, permissions, FEFO, stock, transfers, counts, imports, master APIs, POS) — 87% coverage; frontend 11 Vitest tests; lint/typecheck/build clean
- [x] Live smoke on local stack: create product → stock-in 20 → scan lookup → sell 3 → on-hand 17

## Phase 2 — Seed data
Acceptance: `make seed` completes in < 3 min; dashboards/lists show realistic data.

- [x] Static catalogue: business, 4 demo users (+supplier2), 2 locations, 8 categories, 80 products (HSN/GST/EAN-13), 10 suppliers with price/lead/reliability profiles, festival calendar 2025–2027, approval rules
- [x] 15 months of daily sales (weekly pattern, salary week, festival spikes, noise, trend changes, dead-stock items) bulk-inserted with aggregated sale movements
- [x] 12-month purchasing simulation → POs (grouped per supplier/day), status history, GRNs + batches, invoices, 3-way matches (2 mismatches), late deliveries, damaged goods, open POs in every state
- [x] Historical purchase requests + approvals + feedback (for learning metrics)
- [x] Current batches covering every expiry bucket; warehouse stock + transfers; one completed stock count; injected anomalies
- [x] `python -m app.seed` (idempotent: wipes demo data first), timing printed; seed test
- [x] Verified: full seed 31 s (42k invoices, 84k sale lines, 1.6k POs, 1.6k GRNs/invoices, 885 historical PRs); list APIs < 80 ms; seed tests (consistency, EAN-13, determinism) pass

## Phase 3 — Workflow engine
Acceptance: full purchase cycle works end-to-end in the UI; emails visible in Mailpit; workflow tests pass.

- [x] Services: GST split (CGST/SGST vs IGST), notifications (in-app, email, Telegram when configured), alerts with de-duplication
- [x] PDFs: purchase order (HSN, taxable value, tax split, amount in words, terms), GRN, debit note
- [x] Approval engine: rules → levels (auto / manager / manager+admin), approve / reject (reason) / edit-and-approve, bulk approve, feedback rows
- [x] One-click email/Telegram approval with hashed single-use tokens (48 h) + public confirm page
- [x] SLA reminders (> SLA) and escalation to next role (> 2× SLA) as Celery Beat job
- [x] Purchase orders: grouped from approved requests per supplier+location, PO-YYYYMM-NNNN, PDF + email with portal link, resend, cancel
- [x] Supplier portal: own POs only, confirm / reject, dispatch + ETA + tracking, invoice upload
- [x] GRN with partial receipts, batches + movements, damaged qty → quarantine + return draft
- [x] Supplier invoice + 3-way match (qty 0 %, price 2 %), mismatch alert blocks closing, manager resolution, auto-close
- [x] Supplier returns: approval → debit-note PDF + email → return_out → credit note
- [x] APIs for requests, approvals, approval rules, orders, portal, returns, alerts, notifications
- [x] Frontend: Purchase requests & approvals (explanation panel, edit, bulk), Purchase orders (timeline, PDF, GRN, invoice, match), Supplier portal, Returns, Alerts center, notification bell, one-click approval page, approval rules settings
- [x] Tests: approval routing + multi-level + token single-use/expiry, every invalid transition, GST split, 3-way tolerance, supplier isolation, full cycle
- [x] Verified live (local API, all four roles): manual PR ₹60k → manager → admin → PO auto-created + PDF → supplier2 gets 403 → supplier confirm + dispatch → staff GRN (stock 315 → 4161) → portal invoice → 3-way matched → CLOSED
- [x] Tests: backend 120 passed (86% coverage incl. workflow 88–100%); frontend 16 Vitest tests; lint/typecheck/build clean
- [~] "Emails visible in Mailpit" — email content, recipients and PDF attachments are asserted in tests (APP_ENV=test capture); not seen in a real Mailpit UI because Docker isn't available here and running a downloaded Mailpit binary was not permitted. Run `make up` and open http://localhost:8025.

## Phase 4 — AI agents
Acceptance: running orchestrator on seed data creates sensible purchase requests with explanations, alerts for expiry/low stock/dead stock/anomalies; formula tests pass.

- [x] `app/ml/inventory.py`: z from service level, SS = z·σ·√L, ROP = d̄·L + SS, EOQ = √(2DS/H), order qty (review period, correction factor, perishable cap, pack rounding, MOQ)
- [x] `app/ml/forecast.py`: features (DOW, month, DOM, festival flag, lag 7/14, rolling 7/28), global HistGradientBoosting vs 28-day MA baseline on a 28-day holdout, per-product winner, 30-day recursive forecast with residual-σ interval, model registry + joblib file
- [x] `app/ml/classify.py` ABC (12-month revenue 80/15/5) + XYZ (CV of weekly demand); `app/ml/anomaly.py` rule checks + IsolationForest
- [x] Supplier scoring service (price / on-time / lead / quality with configurable weights) + per-product best supplier with breakdown
- [x] LLM provider abstraction (`none` default, ollama, anthropic, openai via httpx) with rule-based fallbacks (used to polish reason text)
- [x] Agents with `run(context) -> AgentResult` logged to `agent_runs`: StockMonitor, Expiry, Decision, Supplier, AutoOrder, Tracking (+ MockCourierProvider), Anomaly
- [x] Orchestrator: daily pipeline in spec order, per-agent failure isolation, "Run now" per agent; seed runs training + pipeline once
- [x] Celery Beat jobs: pipeline 06:00, quick check every 2 h 08–22, tracking hourly, supplier scores 02:00, weekly ABC/XYZ + anomaly model Sunday 03:00
- [x] APIs: agents + runs, product forecast, ABC/XYZ matrix, dead stock, models, expiry assessment + actions
- [x] Frontend: AI Insights (agents/run now, forecasts, ABC/XYZ matrix, dead stock, anomalies, models), product forecast chart + calc explanation, Expiry page with action buttons
- [x] Tests: formulas, rounding + perishable cap, supplier score, forecast/holdout, ABC/XYZ, anomaly rules, orchestrator on seed data
- [x] Verified on full seed data: all 7 agents succeed (seed + pipeline ≈ 50 s); forecast holdout MAPE 36% (model) vs 44% (MA-28), WAPE 21.6% vs 28.1%, 67/80 products use the model; AI requests carry the spec-style sentence + every input; alerts raised for low/out of stock, all expiry buckets, dead stock, anomalies (5 rules + IsolationForest), late deliveries
- [x] Tests: backend 138 passed (agents/ml 94–100%); frontend 17 Vitest tests; lint/typecheck/build clean

## Phase 5 — Learning, assistant, OCR, simulator
Acceptance: with `LLM_PROVIDER=none` the assistant answers the example questions; OCR pre-fills an invoice from a sample bill image generated in `backend/tests/fixtures/`.

- [x] Learning: daily realised forecast accuracy, rolling 14-day MAPE drift alert (> 1.5× training MAPE), weekly retrain evaluated on the same holdout as the active model and promoted only if better; Learning agent registered for "Run now" + weekly job; seed back-fills 8 weeks of accuracy history
- [x] Correction factor (EMA α = 0.3, clamp 0.5–1.5) applied in Decision (done in phase 4) + rejection streak → lower priority + info alert (phase 3)
- [x] AI Performance API + tab: MAPE trend, suggestion acceptance %, average quantity correction, model versions
- [x] Chat assistant: fixed read-only tools + `draft_purchase_request` (DRAFT only), role-checked; LLM tool-calling loop (anthropic/openai/ollama) with intent-matcher fallback (keywords + RapidFuzz); history stored in `chat_messages`; slide-over panel on every page
- [x] Invoice OCR: Tesseract (+pdf2image) → regex line parser (LLM JSON extraction when enabled) → RapidFuzz product match with per-line confidence → pre-filled invoice form (never auto-saves); sample bill fixture generated in `backend/tests/fixtures/`
- [x] Email quotation reader (IMAP, behind config): parse supplier emails → `supplier_quotes` pending review; hidden when IMAP is not configured
- [x] What-if simulator: demand %, lead-time change, supplier unavailable, service level → new SS/ROP/EOQ/qty, projected stock-outs and cost (no saving)
- [x] RFQs: create for products + suppliers → emails with portal link → supplier quotes in portal → comparison table → "Use this quote" updates supplier prices
- [x] Tests: learning/promotion/drift, assistant intents for every example question, OCR parser + fixture, simulator, RFQ flow, quote parser
- [x] Acceptance (assistant): with `LLM_PROVIDER=none` every example question is answered by the intent matcher (tests: stock level, expiring this week, pending approvals, best supplier, forecast, sales, low stock, draft PR → DRAFT only, role checks); LLM tool loop + fallback tested with a fake provider
- [~] Acceptance (OCR): sample bill generated at `backend/tests/fixtures/sample_bill.png`; parser + fuzzy matching + confidence verified on OCR-style text; the image → Tesseract end-to-end test is skipped on this machine because Tesseract is not installed and installing it was not permitted here (the Docker image installs `tesseract-ocr`; the test runs there)
- [x] Seed now back-fills 56 days of realised accuracy (rolling MAPE 36.6% vs drift threshold 53.2%); seed + pipeline + learning ≈ 72 s
- [x] Tests: backend 160 passed / 1 skipped; frontend 19 Vitest tests; lint/typecheck/build clean

## Phase 6 — Reports, dashboards, polish
Acceptance: Lighthouse PWA installable; every page usable at 360 px; reports export correctly.

- [x] Dashboard API + pages per role: admin/manager KPIs (stock value, below ROP, out of stock, near-expiry value, pending approvals, open POs, late deliveries, month purchases, turnover, AI acceptance %), charts (sales vs forecast, stock value trend, top 10 fast movers, expiry risk by week, supplier on-time %), latest alerts + pending approvals; staff tasks + scan shortcut; supplier → portal
- [x] Reports: stock valuation, sales, purchases, supplier performance, expiry/wastage, GST summary — date filter, PDF + Excel export, report schedules (email)
- [x] Scheduled jobs: daily summary email 21:00, weekly report (PDF + Excel) Monday 08:00, due report schedules, DB backup 01:00 keeping 14
- [x] Backups: create / list / download / restore (admin, typed confirmation)
- [x] PWA: service worker (app-shell cache, offline page) + manifest + icons; installable
- [x] Hindi + Marathi translations for every UI string; language persisted per user
- [x] Responsive pass at 360 px, empty/loading/error states everywhere, dark mode
- [x] Tests: dashboard, report exports (PDF/XLSX parse), backups, schedules
- [x] Acceptance — reports: all six reports export JSON, PDF and XLSX (parametrised tests); GST and sales totals checked arithmetically; scheduled emails carry PDF + Excel attachments
- [x] Acceptance — 360 px: Playwright `responsive.spec.ts` visits 30 pages across all four roles at 360×740 and asserts no horizontal scroll (passing; fixed a chart overflow on the dashboard)
- [~] Acceptance — "Lighthouse PWA installable": Lighthouse itself is not available here; `pwa.spec.ts` checks the same installability criteria (manifest name/start_url/standalone, 192/512 + maskable icons, service worker controlling the page) and that the shell loads offline — passing
- [x] Real `pg_dump` backup verified (3 MB archive); restore requires typing RESTORE
- [x] Tests: backend 172 passed / 1 skipped; frontend 22 Vitest tests (incl. translation key/placeholder parity); Playwright responsive + PWA passing locally

## Phase 7 — Evaluation, tests, docs, hardening
Acceptance: every item in spec section 16 ticked.

- [x] `backend/scripts/evaluate.py` (`make eval`): 90-day backtest — forecast MAPE/RMSE (model vs 28-day MA, weekly rolling origin) and inventory simulation of baseline vs SmartStock policy (stock-out days, fill rate, wasted value, average inventory, orders, purchase cost, on-time %, manual time saved) → `reports/evaluation.md` + PNG charts
- [x] Coverage ≥ 70 % on `services/`, `workflow/`, `agents/`, `ml/`
- [x] Playwright e2e: manager runs orchestrator → approves a purchase request → PO created → supplier confirms + dispatches → staff GRN → stock increased
- [x] Docs: README (overview, features, screenshots section, Mermaid architecture, stack, Docker + non-Docker setup, demo logins, tests, evaluation, env table, troubleshooting incl. Windows), docs/ARCHITECTURE.md (5 layers + learning loop, component + sequence diagrams), docs/USER_GUIDE.md (per role + 10-minute viva script), docs/API.md
- [x] Hardening: security headers, no stack traces to clients, rate-limited login, CORS restricted, secrets only from env (startup warning for default SECRET_KEY in production)
- [x] Final run-through following the README (non-Docker path on this machine) and spec section 16 checklist
- [x] Results (re-run 03-11-2026 on a fresh clone): forecast MAPE 35.2 % vs 40.3 % (MA-28), RMSE 4.60 vs 5.86; stock-out product-days 819 → 210, fill rate 84.5 % → 94.9 %, expired stock ₹10.5 L → ₹0.85 L, on-time 61.2 % → 85.7 %, ≈ 79 h manual time saved; average inventory 2.5× higher (reported as a trade-off)
- [x] Fresh-schema run-through (README non-Docker path): `alembic upgrade head` → `python -m app.seed` in ≈ 2 min (optimised: learning back-fill 52 s → 11 s) → API + preview → all Playwright specs pass
- [x] Final: backend 173 passed / 1 skipped, core-package coverage 90 %; frontend 22 Vitest, lint 0, build OK; Playwright 6/6

## Spec section 16 — Definition of done

- [~] `docker compose up --build` + `make seed` works on a clean machine using only the README — compose file, Dockerfiles and healthchecks are written and the identical commands were verified natively; **Docker is not installed on this build machine, so the containers themselves have not been started.** Run `make up && make seed` once on a Docker machine.
- [x] All 4 roles can log in and see their own dashboard (Playwright: manager, admin, staff, supplier)
- [x] Data input: forms, CSV/Excel import, OCR invoice, browser barcode scan, POS API — OCR verified at parser/matching level; the image→Tesseract test is skipped here (Tesseract not installed locally; installed in the Docker image)
- [x] All 8 agents run from the orchestrator and from "Run now"; runs logged in `agent_runs`
- [x] Purchase cycle request → approval (incl. one-click link) → PO PDF email → supplier confirm/dispatch → GRN → invoice → 3-way match → close (API tests + live run + Playwright)
- [x] Expiry actions, dead stock, anomalies, late deliveries raise alerts and notifications
- [x] Continuous learning visible on AI Performance page; retraining promotes only better models (tested)
- [x] Chat assistant works with and without an LLM (rule-based tests + fake-provider tool loop)
- [x] What-if simulator, RFQs, returns, transfers, stock counts work
- [~] Reports export PDF + Excel (tested); scheduled emails are generated with attachments and sent through SMTP — **not yet seen in a real Mailpit inbox** on this machine (no Docker; running a downloaded Mailpit binary was not permitted)
- [x] English/Hindi/Marathi, dark mode, mobile layout (360 px Playwright check on 30 pages), PWA (installability criteria + offline shell tested; Lighthouse itself not run)
- [x] Backend tests + coverage ≥ 70 % on core packages (90 %); frontend build/lint/tests; Playwright e2e pass
- [x] `make eval` produces `reports/evaluation.md` with charts showing SmartStock vs baseline
- [x] README, ARCHITECTURE, USER_GUIDE (with viva demo script), API, DECISIONS, PROGRESS complete

### Still to verify on a machine with Docker
1. `make up` → all 7 containers healthy; `make seed`; open http://localhost:5173.
2. Mailpit (http://localhost:8025) shows the PO, approval, reminder and scheduled-report emails.
3. `make test` (OCR end-to-end test runs there because the image has Tesseract) and `make e2e`.


## Final audit — 03-11-2026

Fresh `git clone` into an empty folder, followed README "Running without Docker" step by step (new Postgres cluster
via `scripts/dev-db.sh`, new venv, `pip install`, `alembic upgrade head`, `python -m app.seed` 101 s, uvicorn, Celery
worker + beat, `npm ci`, `npm run dev`); `/api/v1/health` reported db, redis, worker and beat ok.

Found and fixed:
- [x] `alembic upgrade head` failed with "No module named 'app'" → `prepend_sys_path = .` in `backend/alembic.ini`
- [x] `cp .env.example .env` broke non-Docker runs (DB/Redis/SMTP hosts and storage paths pointed at containers) → those lines are commented in `.env.example`; compose already sets them for containers
- [x] `make lint LOCAL=1` failed on `ruff format --check` → aligned with the Docker target (`ruff check`)
- [x] `COURIER_PROVIDER` setting was ignored (mock only) → real Shiprocket tracking provider behind config with the simulated fallback (`tests/test_courier.py`)
- [x] Playwright PWA test cannot pass on the Vite dev server (service worker is production-only) → skips there with a reason; README explains running e2e on `npm run preview`
- [x] README placeholders: `git clone <your repo url>` and an empty screenshot gallery → real instructions, 6 screenshots generated by `npm run screenshots`
- [x] Chart ticks rounded 1.5k to "2k" (duplicate labels) on the dashboard and expiry charts
- [x] Single-item columns/labels used plural nav labels ("Suppliers", "Products") on 17 places → `common.supplier` / `common.product` in en/hi/mr
- [x] AI Insights hint said only admins can run the pipeline (managers can) → corrected in en/hi/mr
- [x] Evaluation re-run on the fresh clone; README and report updated with the new numbers

Verified live on the fresh stack (scripted API checks 32/32, Playwright 6/6 on the production build, Hindi/Marathi/dark
mode check, scheduled report email with PDF + XLSX received by a local SMTP server on :1025). Still not possible on
this machine: Docker (not installed), the Mailpit UI itself, Tesseract OCR end-to-end, Lighthouse.
