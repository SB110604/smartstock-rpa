# SmartStock RPA — Setup and Run Guide

This guide takes a new computer from zero to a running SmartStock RPA in about 30 minutes. Pick **one** of the two
options. **Option A (Docker) is recommended** — it installs PostgreSQL, Redis, Mailpit and everything else for you.

---

## 1. What you received

`SmartStock_RPA.zip` contains the complete project:

| Folder / file | What it is |
|---|---|
| `backend/` | Python API (FastAPI), AI agents, database models, tests |
| `frontend/` | React web app (also installable on phones as a PWA) |
| `docker-compose.yml` | Starts all 7 services with one command |
| `Makefile` | Short commands (`make up`, `make seed`, …) |
| `.env.example` | All settings with safe defaults |
| `docs/` | Architecture, user guide, API list, design decisions, progress |
| `reports/` | Evaluation report with charts |
| `scripts/` | Helper scripts (local database for Option B) |

**Extract the zip to a short path without special characters**, for example `C:\Projects\SmartStock_RPA`
(Windows) or `~/Projects/SmartStock_RPA` (macOS/Linux). All commands below are run **inside that folder**.

---

## 2. Option A — Docker (recommended)

### 2.1 Prerequisites

| Item | Version | Where to get it | Notes |
|---|---|---|---|
| Docker Desktop (Windows / macOS) or Docker Engine + Compose v2 (Linux) | 4.x / Compose 2.20+ | https://www.docker.com/products/docker-desktop | On Windows enable **WSL 2** when the installer asks |
| Free disk space | **10 GB** | — | images + database |
| RAM | 8 GB (4 GB free for Docker) | — | |
| GNU Make (optional) | any | Windows: `winget install GnuWin32.Make`; macOS: Xcode tools; Linux: `apt install make` | Without Make, use the `docker compose` commands shown |
| Web browser | Chrome / Edge / Firefox | — | |

Check: open a terminal (Windows: **PowerShell**) and run `docker --version` and `docker compose version`.

### 2.2 First run

```bash
cd C:\Projects\SmartStock_RPA          # the extracted folder
copy .env.example .env                  # macOS/Linux: cp .env.example .env
docker compose up --build -d            # = make up   (first build 5–10 minutes)
docker compose exec -T api python -m app.seed   # = make seed  (1–2 minutes)
```

Wait until `docker compose ps` shows all services **healthy**, then open:

| What | Link |
|---|---|
| **The app** | **http://localhost:5173** |
| E-mail inbox (Mailpit) — every e-mail the system sends | http://localhost:8025 |
| API documentation (try every endpoint) | http://localhost:8000/docs |
| Health check | http://localhost:8000/api/v1/health |

### 2.3 Daily use

| Task | Command |
|---|---|
| Start | `docker compose up -d` (`make up`) |
| Stop (data kept) | `docker compose down` (`make down`) |
| Reset everything (deletes data) | `docker compose down -v`, then the first-run steps |
| Reload demo data | `docker compose exec -T api python -m app.seed` |
| See logs | `docker compose logs -f --tail=100` |

---

## 3. Option B — without Docker (manual)

### 3.1 Prerequisites

| Item | Version | Where to get it |
|---|---|---|
| Python | 3.11, 3.12 or 3.13 | https://www.python.org/downloads/ — tick **"Add python.exe to PATH"** |
| Node.js | 20 LTS or newer | https://nodejs.org |
| PostgreSQL | 16 | https://www.postgresql.org/download/ (Windows installer from EDB) |
| Redis | 7+ | Windows: `winget install Memurai.MemuraiDeveloper` or Redis for Windows; macOS: `brew install redis`; Linux: `apt install redis-server` |
| Git Bash (Windows only) | any | https://git-scm.com — needed for `scripts/dev-db.sh` |
| Tesseract OCR (optional, invoice scanning) | 5.x | Windows: UB-Mannheim build; macOS: `brew install tesseract`; Linux: `apt install tesseract-ocr` |
| Mailpit (optional, to see e-mails) | latest | https://mailpit.axllent.org |

### 3.2 First run (open **four** terminals in the project folder)

**Terminal 1 — database and Redis**
```bash
# Git Bash on Windows; any shell on macOS/Linux
scripts/dev-db.sh start          # creates a private PostgreSQL 16 cluster on port 5433
redis-server                     # skip if Redis/Memurai runs as a Windows service
```
If PostgreSQL is installed somewhere unusual, set `PG_BIN` first, e.g.
`export PG_BIN="/c/Program Files/PostgreSQL/16/bin"`.

**Terminal 2 — backend API**
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate           # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head             # create the 49 tables
python -m app.seed               # demo store + model training (about 2 minutes)
uvicorn app.main:app --port 8000
```

**Terminal 3 — background worker and scheduler**
```bash
cd backend
.venv\Scripts\activate
celery -A app.tasks.celery_app worker -P solo --loglevel=INFO
# in a 5th terminal (same two first lines): celery -A app.tasks.celery_app beat --loglevel=INFO
```

**Terminal 4 — web app**
```bash
cd frontend
npm ci
npm run dev                      # http://localhost:5173
```

Open **http://localhost:5173**. The health page http://localhost:8000/api/v1/health should show db, redis, worker
and beat as `ok`. You do **not** need a `.env` file for Option B — the defaults match this layout.

### 3.3 Next time

Run `scripts/dev-db.sh start`, start Redis, then only the last command of terminals 2, 3 and 4 (after activating the
virtual environment). Stop everything with `Ctrl+C` and `scripts/dev-db.sh stop`.

---

## 4. Logging in

| Role | E-mail | Password | What they see |
|---|---|---|---|
| Admin (owner) | admin@demo.in | Admin@123 | everything + settings, users, audit, backups |
| Manager | manager@demo.in | Manager@123 | dashboards, approvals, AI insights, reports |
| Staff | staff@demo.in | Staff@123 | billing, receiving goods, stock counts |
| Supplier | supplier1@demo.in | Supplier@123 | supplier portal: own orders, invoices, quotes |

**5-minute tour:** log in as manager → *AI Insights* → **Run full pipeline** → *Purchase requests* → open a request
(see "Why the AI suggests this") → approve → open the purchase order. Then log in as **supplier1** and confirm it,
and as **staff** to receive the goods. The full walk-through and viva script are in `docs/USER_GUIDE.md`.

---

## 5. Optional integrations (all work without them)

Edit `.env` (Option A) or set environment variables (Option B), then restart:

| Feature | Settings |
|---|---|
| AI chat with a large language model | `LLM_PROVIDER=ollama` (local, free) or `openai` / `anthropic` + the API key and model name |
| Telegram approval messages | `TELEGRAM_BOT_TOKEN` (the chat id is stored per user) |
| Real e-mail instead of Mailpit | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS=true` |
| Read supplier price e-mails | `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD` |
| Live courier tracking | `COURIER_PROVIDER=shiprocket`, `SHIPROCKET_EMAIL`, `SHIPROCKET_PASSWORD` |

For anything public, change `SECRET_KEY` and set `APP_ENV=production`.

---

## 6. Tests and evaluation

| What | Docker | Without Docker (venv active) |
|---|---|---|
| Backend tests + coverage | `make test` | `cd backend && python -m pytest --cov=app` |
| Frontend lint + tests | `make lint` | `cd frontend && npm run lint && npm test` |
| Browser end-to-end tests | `make e2e` (once: `cd frontend && npx playwright install chromium`) | `npm run build && npm run preview`, then `E2E_BASE_URL=http://localhost:4173 npm run e2e` |
| Evaluation report | `make eval` | `cd backend && python scripts/evaluate.py` → `reports/evaluation.md` |

Expected: 178 backend tests (1 skipped only when Tesseract is missing), 22 frontend tests, 7 browser tests (the PWA one runs on a production build only).

---

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `port is already allocated` / address in use | Another program uses 5173, 8000, 5433, 6379, 1025 or 8025 — close it or change the port in `docker-compose.yml` |
| Login page loads but login fails | The seed has not run — run step "seed" again |
| Health shows `beat: down` for the first minute | Normal — the scheduler reports every 30 s |
| `alembic` / `python` not found | Activate the virtual environment first (`.venv\Scripts\activate`) |
| `scripts/dev-db.sh: not found` on Windows | Run it from **Git Bash**, not PowerShell |
| Docker build fails with "no space left" | Free at least 10 GB, then `docker system prune` |
| Invoice scanning says OCR unavailable | Install Tesseract (Option B) — it is already inside the Docker image |

---

## 8. Final acceptance checklist (do once on the new computer)

These three checks could not be run on the original development machine (no Docker there). They complete the
project's definition of done:

- [ ] `docker compose up --build -d` → `docker compose ps` shows all 7 services healthy → seed → app opens
- [ ] Mailpit (http://localhost:8025) shows the PO, approval and scheduled-report e-mails after the 5-minute tour and *Reports → Schedule → Send now*
- [ ] `make test` passes **with no skipped tests** (the invoice-OCR test runs inside the Docker image)

Tick them in `docs/PROGRESS.md` when done.
