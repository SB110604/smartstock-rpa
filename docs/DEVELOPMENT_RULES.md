# Development rules for this repository

This repo is **SmartStock RPA**, a final-year project: AI-driven intelligent RPA for adaptive business workflow optimization (software only).

**The full specification is in `docs/PROJECT_SPEC.md`. Read it before doing any work in a new session.**
**Progress is tracked in `docs/PROGRESS.md`. Read it at the start of every session and continue from the first unfinished item.**

## How to work
1. Follow the phases in spec section 15 in order. Do not start a phase until the previous phase's acceptance checks pass.
2. Before coding a phase, write a short task list for it in `docs/PROGRESS.md`, then tick items as they are finished.
3. After each meaningful step, run the relevant tests/lint/build and fix failures before moving on. Never leave the build broken.
4. At the end of each phase: run the full test suite, update `docs/PROGRESS.md`, and `git commit -m "phase N: <summary>"`.
5. Keep going through the phases without stopping to ask for confirmation. Only stop and ask if something is truly blocked (for example a missing system dependency you cannot install).
6. Record any design decision not covered by the spec in `docs/DECISIONS.md` (one line each: decision + reason).

## Non-negotiable rules
- Use exactly the tech stack in spec section 2. Do not add new frameworks without recording why in DECISIONS.md.
- No placeholders, TODO stubs, mock pages or fake buttons in the final code. If something needs an external service (LLM, Telegram, IMAP, courier API), implement the real integration behind config **and** a working fallback so the app is fully usable without any API key.
- The LLM never writes SQL or writes to the database directly; it only calls the defined tools.
- All schema changes go through Alembic migrations.
- Every state change in workflows goes through `app/workflow/` and writes status history + audit log.
- Permissions are enforced in the backend, not just hidden in the UI.
- Secrets only from environment variables; keep `.env.example` complete and up to date.
- Keep code typed (Python type hints, TypeScript strict) and lint-clean (ruff, ESLint).
- Must run on Windows (Docker Desktop), macOS and Linux: use LF line endings via `.gitattributes`, no OS-specific paths.

## Useful commands (create these in the Makefile in phase 0)
- `make up` — docker compose up --build -d
- `make down`
- `make migrate` — alembic upgrade head
- `make seed` — load demo data, train models, run orchestrator once
- `make test` — backend pytest with coverage + frontend vitest
- `make e2e` — Playwright test
- `make eval` — run backtest and write reports/evaluation.md
- `make lint`

## Context-saving tips for long sessions
- Don't re-read large files you already know; read only the parts you need.
- When a session's context is getting full, make sure PROGRESS.md says exactly what is done and what is next, commit, and then continue.
