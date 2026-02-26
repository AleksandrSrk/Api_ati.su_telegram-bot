# Copilot / AI agent instructions for this repo

Short, actionable guidance so an AI coding agent becomes productive quickly.

## Big picture
- This project is a Telegram bot that monitors ATI.SU loads and notifies managers.
- Major components:
  - `ati_client.py` — async HTTP client for ATI.SU API; provides `get_my_loads`, `get_load_responses`, `renew_load`, `parse_load`, `get_new_responses`.
  - `telegram_bot.py` — all aiogram handlers, keyboards, and message formatting; uses `dp` and `bot` objects and implements UI flows (manager selection, "My loads", manual/auto renew).
  - `scheduler.py` — APScheduler `AsyncIOScheduler` jobs: `update_loads_job` (hourly renews) and `check_responses_job` (polls new responses). `start_scheduler()` registers jobs for each manager key from config.
  - `state.py` — in-memory runtime state (auto-update flags, known responses, last update time). NOTE: not persisted.
  - `config.py` — environment-based configuration. `MANAGERS` is the canonical list of manager keys used across code.

## Key flows & data shapes (concrete examples)
- Manager identity: code passes a `manager_key` (e.g. "alexander") everywhere. Add/remove managers by editing `config.py` and corresponding env vars.
- Loads: `get_my_loads(manager_key)` returns raw API objects; use `parse_load(load)` to canonicalize fields used by the bot (id, from_city, to_city, weight, can_renew, response_count).
- Responses: call `get_load_responses(manager_key, load_id)`; `ResponseId` is treated as the unique id tracked in `state.known_responses`.
- Renew: call `renew_load(manager_key, load_id)` (handles 200/204 and 429). Caller expects a dict with `success` and optional `reason`.

## Project-specific conventions & patterns
- Manager keys are the single source of truth: use the keys from `MANAGERS` in `config.py` (strings) — used as identifiers in `state`, scheduler job ids, Telegram chat mapping, and HTTP auth.
- `state.py` is process-local: do not assume persistence across restarts. If adding persistence, mirror its structure: `{manager_key: {auto_update, last_update_time, known_responses, responses_initialized}}`.
- `cities.json` is required by `ati_client.city_name()`; if missing, run `fetch_cities.py` or inspect log warning printed at startup.
- First run of `check_responses_job` initializes `known_responses` silently (no notifications). Subsequent runs compare `ResponseId` to detect new responses.

## Integration points & external dependencies
- External: ATI.SU API (base URL in `ati_client.py`) — needs manager access tokens (`MANAGERS[...]['access_token']`).
- External: Telegram Bot API — token via `TELEGRAM_BOT_TOKEN` env var and chat ids via `TELEGRAM_CHAT_ID_*`.
- Async stack: uses `httpx.AsyncClient`, `aiogram` (Dispatcher + polling), and `apscheduler.schedulers.asyncio.AsyncIOScheduler`.

## Developer workflows & common commands
- Run locally (create `.env` from README examples):
  - `python -m venv .venv` (optional)
  - `pip install -r requirements.txt`
  - `python main.py`
- `main.py` starts the scheduler and then `dp.start_polling(bot)` — the process runs the async loop for the bot and scheduler.

## Where to edit for common changes
- Add a manager / change contact_id: `config.py` (update MANAGERS and corresponding env vars).
- Change notification format or message text: `telegram_bot.py` (handlers and `notify_*` functions).
- Change scheduling cadence: `scheduler.py` (`UPDATE_INTERVAL_MINUTES` from env/config).
- Change API interaction or add endpoints: `ati_client.py` (follow existing patterns: async httpx, get_headers(manager_key)).

## Debugging tips (repo-specific)
- Missing `cities.json`: `ati_client` prints a clear warning. Run `fetch_cities.py` or place `cities.json` next to `ati_client.py`.
- Rate limits: `renew_load` returns 429 and the code surfaces a reason — preserve this behavior when modifying HTTP logic.
- Logging: `main.py` sets `logging.basicConfig(level=logging.INFO)`; handlers and modules also print to stdout — prefer `logging` if adding instrumentation.

## Safety checks for edits
- Preserve the `manager_key` flow: any new API call or feature must accept `manager_key` and use `get_headers(manager_key)`.
- Keep `state` shape compatible or migrate carefully (add migration code if switching to persistent storage).

---
If anything is unclear or you'd like this file expanded with code snippets or examples (e.g. how to add a new scheduler job), tell me which area to expand.
