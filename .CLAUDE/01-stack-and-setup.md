# Tech stack and setup

## Language

Python 3.12.3 (README requires a minimum of 3.10+). No other language in the repo.

## Dependencies (`requirements.txt`)

```
fastapi>=0.110.0               # web framework (routing, dependency injection, multipart upload)
uvicorn>=0.29.0                # ASGI server that runs the FastAPI app
jinja2>=3.1.0                  # HTML templating engine (server-side rendering)
python-multipart>=0.0.9        # required by FastAPI to parse multipart forms/uploads
httpx>=0.27.0                  # async HTTP client for API calls (YGOPRODeck, CardTrader)
pydantic>=2.0.0                 # data validation / typed models
opencv-python-headless>=4.9.0   # deterministic CV for the Grading module (no GUI/GTK)
numpy>=1.26.0                   # used by opencv-python-headless
ollama>=0.2.0                   # official client (AsyncClient) for the local Ollama server
python-dotenv>=1.0.0            # loads .env (CARDTRADER_TOKEN) in config.py
pillow>=10.0.0                  # CV image conversion → PNG for base64 embedding in HTML
```

The collection is persisted in **SQLite** (`collection.db`, via the stdlib `sqlite3` module — no
new dependency in `requirements.txt`), no longer in `collection.json` (see
[03-data-models.md](03-data-models.md) and the migration history in
[06-notes-and-discrepancies.md](06-notes-and-discrepancies.md)). `collection.csv` remains a readable
export regenerated on request, not a data source. The interface is served via browser by a local
FastAPI server (`web/`) — no Textual/TUI, no npm/JS build step (htmx is vendored as a
single file in `web/static/`).

## CardTrader (price source — required for any valuation)

The app's only price source is **CardTrader** (`services/cardtrader_api.py`, see
[08-cardtrader-pricing.md](08-cardtrader-pricing.md)), via an authenticated API with a Bearer token.
An `.env` file is needed in the root (copy `.env.example`) with:

```
CARDTRADER_TOKEN=your-token
```

`.env` is in `.gitignore`, never committed. `config.py` loads it with `python-dotenv` at startup
(`load_dotenv()`). Without a valid token, card search (YGOPRODeck) still works, but
no price is ever shown (silent fallback to `€0.00`, never a crash — see
[06-notes-and-discrepancies.md](06-notes-and-discrepancies.md) for the history of how this choice
came about, including the discarded attempt with RapidAPI/Cardmarket).

## Local Ollama server (required only by the "Card Grading" tab)

The Grading module (see [07-grading.md](07-grading.md)) calls a self-hosted **Ollama**
server with the `llava` model, included in the repo as Docker Compose:

```bash
docker compose up -d
```

- `docker-compose.yml` (root) builds `docker/Dockerfile` (based on `ollama/ollama:latest`) and
  mounts a named volume `ollama_data` to persist the downloaded model across restarts.
- `docker/ollama-entrypoint.sh` starts `ollama serve`, waits for it to respond, and runs `ollama pull
  llava` **only if it isn't already present** in the volume — the first startup takes a few
  minutes (downloading a few GB), after that it's instant.
- Exposes the API on `http://localhost:11434` (see `config.OLLAMA_BASE_URL`).
- No API key: the model runs entirely locally, no data leaves the machine.
- If the container isn't running, the "Card Grading" page fails with a readable error
  (`InspectorAgentError`, see [04-services.md](04-services.md)); the other pages of the app are
  unaffected.

## Starting the project

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

`main.py` prints the URL and starts `uvicorn.run("web.app:app", host=config.WEB_HOST,
port=config.WEB_PORT)` — open `http://127.0.0.1:8000` in the browser. `Ctrl+C` to stop the
server. There's no build step (no JS bundling, no `pyproject.toml`/`setup.py`): the front end is
server-side HTML (Jinja2) with vendored htmx, no npm/webpack.

## Environmental note

In the local working directory there is a Python virtualenv **materialized in the repo root**
(`bin/`, `include/`, `lib/`, `lib64/`, `pyvenv.cfg`, `__pycache__/`). These aren't tracked
by git (excluded via `.gitignore`) but do occupy the root — ignore them when exploring the
actual source code, which lives in `services/`, `web/`, and the root modules `config.py`/`models.py`/
`main.py`.

## What's missing (absent from the repo)

- No automated tests (no `pytest`, no `tests/` folder)
- No CI/CD (`.github/workflows/` doesn't exist)
- No `LICENSE`
