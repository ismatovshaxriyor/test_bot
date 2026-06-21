# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Telegram bot for creating, solving, and grading educational tests (quizzes). Written in Uzbek. Two processes run side-by-side:

- **Bot process** (`bot.py`) — python-telegram-bot (v21, async) handling all chat interactions
- **WebApp API** (`api.py`) — FastAPI/uvicorn serving Telegram Mini App HTML pages and REST endpoints

Both share a single SQLite database (`test_bot.db`) via Peewee ORM with WAL mode.

## Running

```bash
# Bot (main process)
python bot.py

# WebApp API (separate terminal, exposed via ngrok)
uvicorn api:app --host 0.0.0.0 --port 8000

# AI extraction standalone test
python scripts/test_extract.py path/to/file.pdf
```

Environment variables are in `.env` (see `.env.example`). Key vars: `BOT_TOKEN`, `ADMIN_ID`, `WEBAPP_URL`, `WEBAPP_VERSION`, `GEMINI_API_KEY`.

When deploying webapp changes: bump `WEBAPP_VERSION` in `.env` to bust Telegram's Mini App cache, then restart both processes.

## Architecture

### Dual data model for tests

Tests have two parallel representations — this is the core invariant:

1. **`Test.correct_answers`** — JSON string (`[{num, type, answer}, ...]`) used for **grading** (`utils.check_answers`). This is the single source of truth for scoring.
2. **`Question` table rows** — rich content (text, options, images) used for **display** in the WebApp. Never used for grading.

Both are created atomically in `services.create_rich_test()`. Any code that creates tests must go through this function to keep them in sync.

### Test creation flows

Three ways to create a test:

- **Legacy** (answer key only): user sends a string like "abcabd" via bot chat → `handlers/test_create.py`
- **AI/file**: user sends PDF/DOCX/image → Gemini extracts questions → fill missing answers/images → `handlers/test_ai_create.py`
- **Manual WebApp**: user fills form in `webapp/create_rich.html` → `POST /api/test/create_rich` → `api.py`

All flows end at `services.create_rich_test()`.

### Question types

- `closed` — 4-choice (A-D)
- `closed6` — 6-choice (A-F)
- `open` — free-text answer
- `open2` — paired answer (a/b), stored as `"val_a||val_b"` canonical form

### Scoring modes

- `simple` — raw correct/total percentage
- `rasch` — IRT Rasch (1PL) model with JMLE estimation; needs 3+ submissions. Implemented in `utils.calculate_rasch_scores()`.

### WebApp authentication

Telegram Mini App `initData` is verified via HMAC-SHA256 in `api.py` (`_verify_init_data`). The `Authorization: tma <initData>` header identifies the user server-side. Test creation via WebApp is admin-only.

### Handler registration order matters

In `bot.py`, handlers are added in a specific order. The global `WEB_APP_DATA` catch-all and `Ortga` button handler must be registered **last** so ConversationHandlers intercept first.

### Membership gating

`membership.py` provides a `@membership_required` decorator. Users must join configured channels before using the bot. Channel list is in the `channels` DB table, managed via `/admin` commands.

### Export

`export.py` generates Excel (openpyxl), PDF (WeasyPrint + Noto fonts from `fonts/`), and chart (matplotlib) exports for test results. DOCX→PDF conversion requires LibreOffice installed.

### LaTeX handling

- `utils.repair_latex_escapes()` — fixes JSON-escaped LaTeX (e.g., `\f` → `\\f`)
- `utils.latex_to_text()` — converts `$...$` LaTeX to Unicode for Telegram chat display
- WebApp renders LaTeX natively (MathLive)

## Key conventions

- All user-facing text is in Uzbek (Latin script)
- HTML parse mode for Telegram messages (`parse_mode="HTML"`)
- Admin check: `ADMIN_ID` from `.env` OR `User.is_admin` flag in DB
- Each handler module exports `get_handlers()` returning a list of handler objects
- Automatic DB backup sent to admin every N hours (configurable via `BACKUP_INTERVAL_HOURS`)
- Database migrations are inline in `database.py` (`_migrate_*` functions), run on every `init_db()` call
