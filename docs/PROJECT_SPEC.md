# PROJECT SPEC — SmartStock RPA

**Project title:** AI-driven Intelligent Robotic Process Automation for Adaptive Business Workflow Optimization
**Product name:** SmartStock RPA
**Type:** Software-only web application. No cameras, RFID, IoT sensors or GPS hardware.

This file is the single source of truth. Build exactly what is described here. When something is not specified, choose the simplest robust option and record the decision in `docs/DECISIONS.md`.

---

## 1. What the system does

A retail/supermarket business uses SmartStock RPA to manage stock and purchasing with AI agents and workflow automation:

1. Product, stock, sales and supplier data enter the system (forms, CSV/Excel import, invoice OCR, barcode scanning in the browser, sales API).
2. Data is validated and stored in PostgreSQL.
3. Eight AI agents, coordinated by an orchestrator, monitor stock, check expiry, forecast demand, decide purchase quantities, pick the best supplier, generate purchase requests, track orders and detect anomalies. A chat assistant answers questions.
4. An RPA workflow engine moves each purchase through: request → approval → purchase order (PDF emailed to supplier) → supplier confirmation/dispatch → goods receipt (GRN) → 3-way match → close. Reminders and escalations run on timers.
5. Role-based dashboards show stock levels, alerts, pending approvals, purchase orders, order tracking, reports and AI performance.
6. Continuous learning: admin approve/reject/edit decisions and new sales data feed back into the models.

---

## 2. Fixed technology choices (do not substitute)

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.x (sync is fine), Alembic migrations, Pydantic v2 |
| Database | PostgreSQL 16 |
| Background jobs | Celery + Redis, Celery Beat for schedules |
| ML | pandas, numpy, scikit-learn (HistGradientBoostingRegressor, IsolationForest), joblib for model files |
| OCR | Tesseract via pytesseract (+ pdf2image for PDFs); RapidFuzz for fuzzy item matching |
| PDF / Excel | ReportLab (PO, GRN, debit note, reports), openpyxl |
| Barcodes | python-barcode + qrcode (generate); html5-qrcode (scan in browser) |
| LLM | Provider abstraction in `app/llm/` supporting `none` (default), `ollama`, `anthropic`, `openai`, selected by `LLM_PROVIDER` env var. **Every LLM feature must have a rule-based fallback so the whole system works with `LLM_PROVIDER=none`.** |
| Email | SMTP; Mailpit container in development (web UI at http://localhost:8025) |
| Telegram | Optional, enabled only when `TELEGRAM_BOT_TOKEN` is set |
| Auth | JWT access + refresh tokens, bcrypt password hashing, optional TOTP 2FA (pyotp) for admin |
| Frontend | React 18 + Vite + TypeScript, Tailwind CSS, React Router, TanStack Query, Recharts, react-hook-form + zod, i18next |
| Tests | pytest (+ httpx TestClient) for backend; Vitest for frontend; Playwright for one end-to-end flow |
| Deployment | Docker Compose: `db`, `redis`, `api`, `worker`, `beat`, `web`, `mailpit` |

Currency is INR (show as ₹). Time zone Asia/Kolkata. Dates DD-MM-YYYY in the UI.

---

## 3. Repository layout

```
smartstock-rpa/
├─ docs/DEVELOPMENT_RULES.md
├─ README.md
├─ docker-compose.yml
├─ .env.example
├─ Makefile                      # make up, make seed, make test, make eval
├─ docs/
│  ├─ PROJECT_SPEC.md            # this file
│  ├─ PROGRESS.md                # phase checklist, kept up to date
│  ├─ DECISIONS.md               # design decisions made during the build
│  ├─ ARCHITECTURE.md            # final architecture + diagram (Mermaid)
│  ├─ API.md                     # endpoint summary (FastAPI /docs is the full reference)
│  └─ USER_GUIDE.md              # how each role uses the system, with demo script
├─ backend/
│  ├─ Dockerfile                 # installs tesseract-ocr + poppler-utils
│  ├─ pyproject.toml / requirements.txt
│  ├─ alembic/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ core/                   # config, security, deps, permissions, logging
│  │  ├─ db/                     # session, base
│  │  ├─ models/                 # SQLAlchemy models
│  │  ├─ schemas/                # Pydantic schemas
│  │  ├─ api/v1/                 # routers
│  │  ├─ services/               # business logic (stock, purchasing, gst, pdf, notify, import, ocr)
│  │  ├─ workflow/               # state machines + approval engine
│  │  ├─ agents/                 # orchestrator + 8 agents
│  │  ├─ ml/                     # forecasting, anomaly, training, evaluation
│  │  ├─ llm/                    # provider abstraction + fallbacks
│  │  ├─ tasks/                  # Celery tasks + beat schedule
│  │  └─ seed/                   # deterministic demo data generator
│  ├─ scripts/evaluate.py        # backtest + metrics report
│  └─ tests/
└─ frontend/
   ├─ Dockerfile
   ├─ src/
   │  ├─ api/  components/  pages/  hooks/  i18n/ (en, hi, mr)  layouts/  lib/
   └─ tests/
```

---

## 4. Roles and permissions

| Role | Can do |
|---|---|
| **Admin** (owner) | Everything: users, settings, approval rules, final approvals above manager limit, model retraining, audit log |
| **Manager** | Products, suppliers, stock, purchase requests, approvals within limit, POs, GRN, reports, AI insights |
| **Staff** | Stock-in/out, barcode scanning, sales entry, stock counts, GRN entry, view alerts |
| **Supplier** | Own login; sees only their POs and RFQs; confirms/rejects POs, enters dispatch details and ETA, submits quotations, uploads invoice |

Enforce permissions in the backend (dependency per route) and hide unavailable UI in the frontend. Write tests proving a staff user and a supplier user get 403 on manager/admin routes, and a supplier cannot read another supplier's POs.

---

## 5. Data model (minimum; add columns as needed)

- **users**: id, name, email (unique), phone, password_hash, role, supplier_id (nullable), language, totp_secret (nullable), is_active, created_at
- **settings** (key/value JSON): business name, address, state, GSTIN, ordering_cost_S (default ₹500), holding_cost_pct (default 20%/year), service_level (default 0.95), review_period_days (7), supplier score weights, expiry thresholds, notification channels, approval SLA hours
- **locations**: id, name, type (store/warehouse) — seed one store + one warehouse; stock is per location
- **categories**: id, name
- **products**: id, sku, barcode, name, category_id, unit, hsn_code, gst_rate, cost_price, selling_price, is_perishable, shelf_life_days, min_order_qty, pack_size, reorder_point (computed), safety_stock (computed), eoq (computed), abc_class, xyz_class, is_active
- **suppliers**: id, name, contact_name, email, phone, gstin, state, payment_terms_days, is_active
- **supplier_products**: supplier_id, product_id, unit_price, lead_time_days, min_order_qty, valid_till
- **batches**: id, product_id, location_id, batch_no, expiry_date, qty_on_hand, cost_price, received_at, grn_line_id
- **stock_movements**: id, product_id, batch_id, location_id, type (purchase_in, sale_out, adjustment, transfer_in, transfer_out, return_out, write_off), qty (signed), reference_type, reference_id, user_id, note, created_at
- **sales** + **sale_lines**: id, invoice_no, location_id, sold_at, channel (pos_api/manual), total; lines with product_id, batch_id, qty, unit_price
- **stock_counts** + lines (cycle count with variance)
- **forecasts**: product_id, date, predicted_qty, lower, upper, model_name, model_version
- **model_registry**: name, version, trained_at, metrics JSON (MAPE, RMSE), is_active, file_path
- **purchase_requests**: id, product_id, location_id, suggested_qty, final_qty, suggested_supplier_id, final_supplier_id, est_unit_price, est_total, reason_json (all inputs used), reason_text, created_by (agent/user), status, created_at
- **approval_rules**: id, min_amount, max_amount, approver_role, auto_approve (bool) — seed: ≤ ₹5,000 auto-approve; ₹5,000–50,000 manager; > ₹50,000 admin
- **approvals**: id, purchase_request_id, level, approver_id, decision, comment, decided_at, via (web/email_link/telegram)
- **approval_tokens**: token_hash, approval_id, action, expires_at, used_at
- **rfqs** + **rfq_items** + **supplier_quotes**
- **purchase_orders**: id, po_no, supplier_id, location_id, status, order_date, expected_date, predicted_date, subtotal, cgst, sgst, igst, total, pdf_path, sent_at, confirmed_at, dispatched_at, tracking_ref, delivered_at, closed_at
- **po_lines**: po_id, product_id, qty, unit_price, gst_rate, received_qty
- **order_status_history**: po_id, from_status, to_status, note, actor_type, actor_id, created_at
- **goods_receipts** + **grn_lines**: po_line_id, received_qty, damaged_qty, batch_no, expiry_date
- **supplier_invoices** + lines (entered manually or via OCR)
- **three_way_matches**: po_id, grn_id, invoice_id, status (matched/mismatch), details_json
- **supplier_returns** + lines + debit note PDF
- **supplier_scores**: supplier_id, computed_at, price_score, on_time_pct, avg_lead_days, lead_score, reject_pct, quality_score, total_score
- **alerts**: id, type (low_stock, expiry_warning, expiry_critical, expired, dead_stock, anomaly, late_delivery, approval_pending, three_way_mismatch, forecast_drift), severity, product_id, ref_type, ref_id, message, status (open/acknowledged/resolved), created_at
- **notifications**: user_id, channel (in_app/email/telegram), alert_id, title, body, sent_at, read_at
- **agent_runs**: agent_name, started_at, finished_at, status, items_processed, summary_json, error
- **feedback**: purchase_request_id, suggested_qty, final_qty, decision, reason, product_id — used for learning
- **audit_log**: user_id, action, entity, entity_id, before_json, after_json, ip, created_at (written for every create/update/delete via a service-layer helper)
- **chat_messages**: user_id, role, content, tool_calls_json, created_at

All tables have created_at/updated_at. Use Alembic for every schema change.

---

## 6. Data input (Layer 1)

1. **Forms** for every master entity with validation and search/filter/pagination tables.
2. **CSV/Excel import** for products, suppliers, supplier prices, opening stock (with batches), sales history. Flow: upload → column-mapping screen (auto-match by header name) → preview with per-row errors → commit valid rows → downloadable error report. Provide template files to download.
3. **Barcode labels**: generate printable label sheets (PDF, Code128 + QR) for products and batches.
4. **Browser barcode scanning** (html5-qrcode) on Stock-in, Stock-out, Sales and Stock-count screens; works with laptop webcam and phone camera; manual SKU search as fallback.
5. **Invoice OCR**: upload JPG/PNG/PDF of a supplier bill → Tesseract text → line parsing (regex rules; LLM structured extraction when enabled) → RapidFuzz match to products → pre-filled supplier-invoice / stock-in form for the user to confirm. Show the confidence per line; never save without confirmation.
6. **Sales API**: `POST /api/v1/integrations/pos/sales` with API-key auth for external POS; plus a simple built-in billing screen.
7. **Email quotation reader** (Advanced): when IMAP settings exist, a Celery task reads supplier emails and extracts price updates into `supplier_quotes` as *pending review*. Without IMAP config the feature is hidden.

---

## 7. AI agents (Layer 3)

Implement each agent as a class with `run(context) -> AgentResult`, logged to `agent_runs`. The **Orchestrator** runs the daily pipeline in this order and passes results along:

`StockMonitor → Expiry → Decision (forecast + ROP + EOQ) → Supplier → AutoOrder → Tracking → Anomaly`

The orchestrator also exposes "Run now" per agent for the admin (button in UI) and handles failures per agent without stopping the rest.

### 7.1 Stock Monitor agent
- Computes on-hand (sum of batch qty, excluding expired), on-order (open PO lines not yet received) and available per product per location.
- Raises `low_stock` alert when available ≤ reorder_point; `out_of_stock` when 0.
- Dead-stock detection: no sales in N days (default 60) with qty > 0 → `dead_stock` alert with suggestion (clearance discount, bundle, stop reordering).
- ABC (by 12-month revenue: A = top 80%, B = next 15%, C = rest) and XYZ (coefficient of variation of weekly demand: X < 0.5, Y < 1.0, Z ≥ 1.0) classification, recalculated weekly.

### 7.2 Expiry agent
- For each batch: days_to_expiry. Thresholds (settings): expired ≤ 0, critical ≤ 7, warning ≤ 30.
- Projected sell-through = avg daily sales × days_to_expiry. If projected < batch qty → at-risk.
- Actions: expired → block from sale, suggest write-off or supplier return; critical at-risk → suggest 30% markdown; warning at-risk → suggest 10–15% markdown or transfer to other location.
- Sales and stock-out always pick **FEFO** (earliest-expiry batch first) automatically.

### 7.3 Decision agent (forecast + reorder logic)
- **Forecast model**: per product, daily demand with features: day of week, month, day of month, holiday/festival flag (Indian festival calendar table: Diwali, Holi, Ganesh Chaturthi, Navratri, Eid, Christmas, New Year, Makar Sankranti, Independence Day — seed dates for 2025–2027), lag_7, lag_14, rolling_mean_7, rolling_mean_28. Model: HistGradientBoostingRegressor (global model across products with product_id/category as features is acceptable). Baseline: 28-day moving average. Hold out last 28 days; keep whichever has lower MAPE per product; store metrics in `model_registry`. Forecast 30 days ahead with simple prediction interval (residual std).
- **Safety stock** SS = z × σ_d × √L (z from service_level; σ_d = std of daily demand; L = lead time of chosen supplier).
- **Reorder point** ROP = d̄ × L + SS (d̄ = mean forecast daily demand over the next L days).
- **EOQ** = √(2DS / H), D = annual demand (forecast × 365), S = ordering cost, H = holding_cost_pct × unit cost.
- **Order quantity** = max(EOQ, ROP + d̄ × review_period − (on_hand + on_order)), rounded up to pack_size and ≥ min_order_qty. For perishables cap at d̄ × shelf_life_days × 0.8.
- Apply **learning correction** (7.9) to the quantity.
- Output a recommendation with `reason_json` containing every input and `reason_text` like: "Forecast 120 units over next 11 days (lead 4 + review 7). On hand 18, on order 0, safety stock 22. Suggest 130 (EOQ 110, rounded to pack of 10)."

### 7.4 Supplier agent
- Supplier score (0–100) per supplier, recomputed nightly from history:
  `score = w_price·price_score + w_ontime·on_time_pct + w_lead·lead_score + w_quality·quality_score`
  defaults 0.35 / 0.30 / 0.20 / 0.15 (editable in settings). price_score = 100 × min_price / supplier_price for that product; lead_score = 100 × min_lead / supplier_lead; quality_score = 100 − reject_pct.
- Picks the best supplier per product and returns a breakdown that the UI shows as a small bar chart.
- **RFQ**: manager can create an RFQ for selected products and suppliers → emails with portal link → suppliers submit quotes in portal → comparison table → "Use this quote" updates supplier_products.

### 7.5 Auto-order agent
- Creates `purchase_requests` from Decision + Supplier outputs (one per product; skip if an open request/PO already covers it).
- Groups approved requests by supplier and location into one PO.
- Uses the LLM (if enabled) only to polish `reason_text`; fallback is the template sentence.
- Routes each request to the approval engine (8.1).

### 7.6 Tracking agent
- Predicts delivery date per PO = order_date + supplier mean lead time (from history); flags `late_delivery` risk when today > predicted date and not delivered, or supplier ETA > required date.
- Sends reminders to supplier for unconfirmed POs after 24 h; escalates to manager after 48 h.
- Order timeline from `order_status_history`.
- Optional courier tracking via a `CourierProvider` interface with a `MockCourierProvider` (default) that advances status realistically for demo.

### 7.7 Anomaly agent
- Rule checks: stock adjustment beyond 3σ of that product's adjustments, negative-stock attempts, cost price change > 20%, sales spike > 3× rolling mean, repeated manual corrections by the same user.
- IsolationForest on movement features (qty, hour, weekday, user, type, value) trained weekly; flag top anomalies.
- Each anomaly → alert with explanation; admin can mark "valid" or "investigate".

### 7.8 Chat assistant
- Chat panel in the UI. Supports questions like: "How much rice is left?", "Which items expire this week?", "Show pending approvals", "Best supplier for sugar?", "Create a purchase request for 50 kg sugar".
- Implementation: a fixed set of **tools** (Python functions with read-only queries + one `draft_purchase_request` tool that only creates a DRAFT needing normal approval). With an LLM enabled, use tool calling. With `LLM_PROVIDER=none`, use an intent matcher (keywords + RapidFuzz on product names) mapping to the same tools.
- The LLM never writes SQL and never writes to the DB directly. Respect the user's role in every tool.

### 7.9 Continuous learning
- Every approval decision writes to `feedback`.
- Per product correction factor = exponential moving average (α = 0.3) of final_qty / suggested_qty over approved requests, clamped to [0.5, 1.5], applied in 7.3.
- Rejection reasons are counted; if a product's suggestions are rejected 3 times in a row, lower its priority and raise an info alert.
- Weekly retraining task: retrain forecast model, compare MAPE with active model on the same holdout, promote only if better, log in `model_registry`.
- Forecast-drift alert when the rolling 14-day MAPE exceeds 1.5× the training MAPE.
- "AI Performance" page: forecast MAPE trend, acceptance rate of suggestions, average quantity correction, model versions.

---

## 8. Workflow automation (Layer 4 — RPA engine)

Implement explicit state machines with allowed transitions in one place (`app/workflow/`), every transition writing history + audit log + notifications. Invalid transitions return 409.

### 8.1 Purchase request & approval
States: `DRAFT → PENDING_APPROVAL → APPROVED | REJECTED → ORDERED` (+ `CANCELLED`).
- Approval engine reads `approval_rules` by estimated total: auto-approve, manager, or admin (admin-level requests need manager then admin = two levels).
- Approver can approve, reject (reason required), or edit quantity/supplier then approve.
- **One-click approval**: email (and Telegram if enabled) with Approve / Reject links using signed, single-use tokens valid 48 h; reject link opens a tiny page asking for a reason.
- SLA: pending > `approval_sla_hours` (default 24) → reminder; > 2× → escalate to next role.
- Bulk approve on the approvals page.

### 8.2 Purchase order
States: `CREATED → SENT → CONFIRMED → DISPATCHED → PARTIALLY_RECEIVED → RECEIVED → INVOICED → CLOSED` (+ `REJECTED_BY_SUPPLIER`, `CANCELLED`).
- PO number format `PO-YYYYMM-0001`.
- PO PDF (ReportLab): business header, supplier, GSTIN, lines with HSN, qty, rate, taxable value, CGST/SGST (same state) or IGST (different state), totals in figures and words, terms.
- On approval: PDF generated and emailed to supplier with portal link automatically.
- Supplier confirms/rejects and enters dispatch details + ETA in the portal.

### 8.3 Goods receipt (GRN)
- Staff open a PO, scan or enter received qty, damaged qty, batch number, expiry date per line. Partial receipts allowed.
- Creates batches + stock movements; damaged qty goes to a supplier return draft.

### 8.4 Supplier invoice + 3-way match
- Invoice entered manually or via OCR (6.5).
- Match PO vs GRN vs invoice per line: qty tolerance 0%, price tolerance 2% (settings). Result matched/mismatch with details; mismatch raises alert and blocks closing until resolved by manager.

### 8.5 Supplier returns
Return request → approval → debit-note PDF → stock movement `return_out` → status tracking until credit note received.

### 8.6 Stock transfer between locations
Request → approve → dispatch → receive, with movements on both sides.

### 8.7 Scheduled jobs (Celery Beat, Asia/Kolkata)
| Job | When |
|---|---|
| Orchestrator full pipeline | daily 06:00 |
| Stock monitor + expiry quick check | every 2 hours, 08:00–22:00 |
| Approval SLA reminders / escalations | every 30 min |
| Tracking agent | every hour |
| Supplier scores | daily 02:00 |
| ABC/XYZ + anomaly model training + forecast retraining | weekly Sunday 03:00 |
| Daily summary email to manager | daily 21:00 |
| Weekly report (PDF + Excel) to admin | Monday 08:00 |
| Database backup (pg_dump to `backups/`, keep 14) | daily 01:00 |

---

## 9. Output (Layer 5) — frontend pages

Layout: sidebar navigation, top bar with search, notification bell (unread count, dropdown), language switch (English / हिन्दी / मराठी), dark mode toggle, user menu. Responsive down to 360 px width; installable PWA (manifest + service worker). Loading skeletons, empty states and error toasts on every page.

1. **Login** (+ 2FA step when enabled), forgot password via email link.
2. **Dashboard** (role-based):
   - Admin/Manager: KPI cards — stock value, items below reorder point, out of stock, near-expiry value, pending approvals, open POs, late deliveries, this month's purchases, inventory turnover, AI suggestion acceptance %. Charts — sales vs forecast (30 days), stock value trend, top 10 fast movers, expiry risk by week, supplier on-time %. Lists — latest alerts, pending approvals.
   - Staff: tasks for today (GRNs to receive, stock counts, expiring items to move), scan shortcut.
   - Supplier: open POs, RFQs awaiting quote, performance score.
3. **Products** (list, create/edit, detail page with stock by batch/location, movement history, forecast chart with interval, ROP/SS/EOQ values and how they were computed, suppliers and prices).
4. **Stock**: stock-in, stock-out, adjustments (reason required), transfers, stock count with variance report, scanning on all.
5. **Sales**: simple billing screen with scanner, sales history.
6. **Expiry**: batches grouped by expired / critical / warning with suggested action buttons (apply markdown, create return, transfer, write-off).
7. **Suppliers**: list, detail with score breakdown chart, price list, PO history, on-time trend.
8. **RFQs**: create, track responses, compare quotes.
9. **Purchase requests & Approvals**: queue with filters, AI explanation panel, edit-and-approve, bulk actions, approval history.
10. **Purchase orders**: list with status chips, detail with timeline, PDF download, resend email, GRN, invoice, 3-way match result.
11. **Supplier portal** (same app, supplier role): POs, confirm/reject, dispatch + ETA, quotes, invoice upload.
12. **Alerts center**: filters by type/severity/status, acknowledge/resolve.
13. **AI Insights**: agent run history with "Run now", forecasts per product, ABC/XYZ matrix, dead stock, anomalies, AI performance (7.9).
14. **What-if simulator**: inputs — demand change %, lead time change, supplier unavailable, service level; output — new ROP/EOQ/order quantities, projected stock-outs and cost, without saving.
15. **Reports**: stock valuation, sales, purchases, supplier performance, expiry/wastage, GST summary — date filter, export PDF and Excel; schedule email.
16. **Import center**: templates, upload, mapping, preview, results.
17. **Labels**: print barcode labels.
18. **Chat assistant**: slide-over panel available on every page.
19. **Settings** (admin): business profile, users, approval rules, thresholds, cost parameters, score weights, notification channels, LLM provider status, API keys for POS, backup/restore.
20. **Audit log** (admin) with filters and before/after diff.

---

## 10. API

- REST under `/api/v1`, JSON, pagination (`page`, `page_size`, `total`), filtering and sorting on list endpoints, consistent error format `{ "detail": ..., "code": ... }`.
- OpenAPI at `/docs`. Health check `/api/v1/health` (db, redis, worker status).
- Rate-limit login; CORS restricted to the frontend origin; all secrets from env vars.
- Summarise endpoints in `docs/API.md`.

---

## 11. Seed / demo data (deterministic, `make seed`)

Generator with a fixed random seed producing a realistic Indian supermarket:
- Business "Shree Ganesh SuperMart", Pune, Maharashtra (GSTIN format valid-looking test value).
- Users with documented passwords: `admin@demo.in / Admin@123`, `manager@demo.in / Manager@123`, `staff@demo.in / Staff@123`, `supplier1@demo.in / Supplier@123` (linked to a supplier). Print them in README.
- 2 locations, 8 categories (staples, dairy, beverages, snacks, personal care, household, packaged food, fruits & vegetables), 80 products with realistic names, HSN codes and GST rates (0/5/12/18%), perishables with shelf lives.
- 10 suppliers (mix of Maharashtra and other states to exercise CGST/SGST vs IGST) with different price/lead-time/reliability profiles (one cheap but late, one reliable but expensive, etc.).
- 15 months of daily sales history ending yesterday: base demand per product, weekly pattern (weekends higher), monthly salary-week bump, festival spikes (Diwali, Ganesh Chaturthi, Holi, Navratri…), noise, a few trend changes.
- 12 months of historical POs, GRNs and invoices consistent with the sales, with realistic lead times, some late deliveries, some damaged goods, two 3-way mismatches.
- Current batches with spread of expiry dates so every expiry bucket has items; a few dead-stock items; a few injected anomalies.
- After seeding, run model training and the orchestrator once so the dashboard is populated on first login.

---

## 12. Evaluation (`make eval` → `reports/evaluation.md` + PNG charts)

Backtest over the last 90 days of seeded data, comparing:
- **Baseline policy**: fixed reorder level = 7 days of average sales, fixed order qty = 14 days of average sales, cheapest supplier.
- **SmartStock policy**: forecast + ROP + EOQ + supplier scoring + FEFO + expiry markdowns.

Report: forecast MAPE and RMSE (model vs moving average), stock-out days, fill rate, expired/wasted stock value, average inventory value, number of orders, total purchase cost, on-time delivery %, and estimated manual time saved (assume 15 min per manual PO vs 2 min with approval). Include tables and charts. These numbers go into the project report.

---

## 13. Quality bar

- No placeholder pages, no "TODO" stubs, no lorem ipsum, no fake buttons. Every button works.
- Backend test coverage ≥ 70% for `services/`, `workflow/`, `agents/`, `ml/`. Must include tests for: ROP/SS/EOQ formulas, order-quantity rounding and perishable cap, supplier score, FEFO picking, GST split, approval routing + multi-level + token single-use + expiry, every invalid workflow transition, 3-way match tolerance, permissions, CSV import validation, chat intent fallback.
- Frontend: `npm run build` and `npm run lint` pass with no errors; Vitest tests for key components; Playwright e2e: login as manager → run orchestrator → approve a purchase request → PO created → login as supplier → confirm + dispatch → login as staff → GRN → stock increased.
- Type hints throughout backend; ruff clean. ESLint + Prettier on frontend.
- Structured logging; errors never leak stack traces to the UI.
- `docker compose up --build` then `make seed` must give a working system on a clean machine (Windows with Docker Desktop, macOS, Linux).

---

## 14. Documentation to produce

- **README.md**: overview, features list, screenshots section (placeholders for images the student will add), architecture diagram (Mermaid), tech stack, setup (Docker and non-Docker), demo logins, how to run tests and evaluation, environment variables table, troubleshooting (Windows notes: line endings, Docker Desktop memory, ports).
- **docs/ARCHITECTURE.md**: 5-layer architecture matching the project report (Data input → Processing & storage → Agentic AI → Automation → Output, with continuous learning loop), component and sequence diagrams (Mermaid) for the purchase flow.
- **docs/USER_GUIDE.md**: step-by-step per role + a 10-minute viva demo script.
- **docs/API.md**, **docs/DECISIONS.md**, **docs/PROGRESS.md**.

---

## 15. Build phases and acceptance checks

Work strictly in this order. A phase is done only when its checks pass. Update `docs/PROGRESS.md` and commit at the end of each phase with message `phase N: <summary>`.

**Phase 0 — Scaffold**
Monorepo, Docker Compose with all services, backend app factory, health endpoint, Alembic, frontend Vite app with layout shell, Tailwind, router, i18n, lint/test tooling, Makefile, `.env.example`.
✅ `docker compose up --build` starts all containers healthy; `/api/v1/health` OK; frontend loads; `make test` runs.

**Phase 1 — Core data & auth**
All models + migrations, auth (JWT, refresh, roles, 2FA), users, settings, locations, categories, products, suppliers, supplier_products, batches, stock movements with FEFO, sales, stock counts, transfers, audit log, CRUD UI pages, CSV/Excel import center, barcode labels + browser scanning.
✅ Tests for auth, permissions, FEFO, import validation pass; can create products, receive stock, sell by scanning, see stock update.

**Phase 2 — Seed data**
Deterministic generator (section 11).
✅ `make seed` completes in < 3 min; dashboards/lists show realistic data.

**Phase 3 — Workflow engine**
Purchase requests, approval rules & multi-level approvals, one-click email/Telegram links, PO + PDF + GST + email, supplier portal, GRN, supplier invoice, 3-way match, returns + debit note, transfers, notifications (in-app + email via Mailpit), alerts center, Celery + Beat jobs, SLA reminders/escalations.
✅ Full purchase cycle works end-to-end in the UI; emails visible in Mailpit; workflow tests pass.

**Phase 4 — AI agents**
Orchestrator + all 8 agents (section 7), model registry, agent run logging, AI Insights page, explanation panel on approvals.
✅ Running orchestrator on seed data creates sensible purchase requests with explanations, alerts for expiry/low stock/dead stock/anomalies; formula tests pass.

**Phase 5 — Learning, assistant, OCR, simulator**
Feedback loop + correction factor, retraining with promotion, drift alert, AI Performance page, chat assistant (LLM + fallback), invoice OCR, email quotation reader (behind config), what-if simulator, RFQs.
✅ With `LLM_PROVIDER=none` the assistant answers the example questions; OCR pre-fills an invoice from a sample bill image you generate in `backend/tests/fixtures/`.

**Phase 6 — Reports, dashboards, polish**
All dashboards and charts, reports with PDF/Excel export and scheduled emails, dark mode, Hindi + Marathi translations, PWA, responsive check, empty/loading/error states, backups.
✅ Lighthouse PWA installable; every page usable at 360 px; reports export correctly.

**Phase 7 — Evaluation, tests, docs, hardening**
`scripts/evaluate.py`, coverage target, Playwright e2e, all documentation, final clean-machine run-through following README only.
✅ Every item in section 16 ticked.

---

## 16. Definition of done (final checklist)

- [ ] `docker compose up --build` + `make seed` works on a clean machine using only the README
- [ ] All 4 roles can log in and see their own dashboard
- [ ] Data input: forms, CSV/Excel import, OCR invoice, browser barcode scan, POS API
- [ ] All 8 agents run from the orchestrator and from "Run now"; runs logged
- [ ] Purchase cycle request → approval (incl. one-click link) → PO PDF email → supplier confirm/dispatch → GRN → invoice → 3-way match → close
- [ ] Expiry actions, dead stock, anomalies, late deliveries raise alerts and notifications
- [ ] Continuous learning visible on AI Performance page; retraining promotes only better models
- [ ] Chat assistant works with and without an LLM
- [ ] What-if simulator, RFQs, returns, transfers, stock counts work
- [ ] Reports export PDF + Excel; scheduled emails arrive in Mailpit
- [ ] English/Hindi/Marathi, dark mode, mobile layout, PWA
- [ ] Backend tests + coverage ≥ 70% on core packages; frontend build/lint/tests; Playwright e2e pass
- [ ] `make eval` produces `reports/evaluation.md` with charts showing SmartStock vs baseline
- [ ] README, ARCHITECTURE, USER_GUIDE (with viva demo script), API, DECISIONS, PROGRESS complete
