# Stack tecnologico e setup

## Linguaggio

Python 3.12.3 (README richiede minimo 3.10+). Nessun altro linguaggio nel repo.

## Dipendenze (`requirements.txt`)

```
fastapi>=0.110.0               # framework web (route, dependency injection, upload multipart)
uvicorn>=0.29.0                # server ASGI che esegue l'app FastAPI
jinja2>=3.1.0                  # motore di template HTML (server-side rendering)
python-multipart>=0.0.9        # richiesto da FastAPI per parsare form/upload multipart
httpx>=0.27.0                  # client HTTP asincrono per le chiamate API (YGOPRODeck, CardTrader)
pydantic>=2.0.0                 # validazione dati / modelli tipizzati
opencv-python-headless>=4.9.0   # CV deterministica per il modulo di Grading (no GUI/GTK)
numpy>=1.26.0                   # usato da opencv-python-headless
ollama>=0.2.0                   # client ufficiale (AsyncClient) verso il server Ollama locale
python-dotenv>=1.0.0            # carica .env (CARDTRADER_TOKEN) in config.py
pillow>=10.0.0                  # conversione immagini CV → PNG per l'embed base64 nell'HTML
```

La collezione è persistita in **SQLite** (`collection.db`, via il modulo stdlib `sqlite3` — nessuna
nuova dipendenza in `requirements.txt`), non più su `collection.json` (vedi
[03-modelli-dati.md](03-modelli-dati.md) e la cronologia della migrazione in
[06-note-e-discrepanze.md](06-note-e-discrepanze.md)). `collection.csv` resta un export leggibile
rigenerato su richiesta, non una fonte di dati. L'interfaccia è servita via browser da un server
FastAPI locale (`web/`) — niente Textual/TUI, niente npm/build step JS (htmx è vendorizzato come
singolo file in `web/static/`).

## CardTrader (fonte prezzi — richiesto per qualsiasi valorizzazione)

L'unica fonte di prezzo dell'app è **CardTrader** (`services/cardtrader_api.py`, vedi
[08-pricing-cardtrader.md](08-pricing-cardtrader.md)), via API autenticata con Bearer token.
Serve un file `.env` in root (copiare `.env.example`) con:

```
CARDTRADER_TOKEN=il-tuo-token
```

`.env` è in `.gitignore`, mai committato. `config.py` lo carica con `python-dotenv` all'avvio
(`load_dotenv()`). Senza token valido, la ricerca carte (YGOPRODeck) funziona comunque, ma
nessun prezzo viene mai mostrato (fallback silenzioso a `€0.00`, mai un crash — vedi
[06-note-e-discrepanze.md](06-note-e-discrepanze.md) per la storia di come si è arrivati a
questa scelta, incluso il tentativo scartato con RapidAPI/Cardmarket).

## Server Ollama locale (richiesto solo dal tab "Grading Carta")

Il modulo di Grading (vedi [07-grading.md](07-grading.md)) chiama un server **Ollama**
self-hosted col modello `llava`, incluso nel repo come Docker Compose:

```bash
docker compose up -d
```

- `docker-compose.yml` (root) builda `docker/Dockerfile` (basato su `ollama/ollama:latest`) e
  monta un volume nominato `ollama_data` per persistere il modello scaricato tra i riavvii.
- `docker/ollama-entrypoint.sh` avvia `ollama serve`, attende che risponda, e fa `ollama pull
  llava` **solo se non è già presente** nel volume — al primo avvio richiede qualche minuto
  (download di alcuni GB), poi è immediato.
- Espone l'API su `http://localhost:11434` (vedi `config.OLLAMA_BASE_URL`).
- Nessuna API key: il modello gira interamente in locale, nessun dato lascia la macchina.
- Se il container non è in esecuzione, la pagina "Grading Carta" fallisce con un errore leggibile
  (`InspectorAgentError`, vedi [04-servizi.md](04-servizi.md)); le altre pagine dell'app non ne
  risentono.

## Avvio del progetto

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

`main.py` stampa l'URL e avvia `uvicorn.run("web.app:app", host=config.WEB_HOST,
port=config.WEB_PORT)` — apri `http://127.0.0.1:8000` nel browser. `Ctrl+C` per fermare il
server. Non esiste build step (no bundling JS, no `pyproject.toml`/`setup.py`): il front-end è
HTML server-side (Jinja2) con htmx vendorizzato, nessun npm/webpack.

## Nota ambientale

Nella working directory locale è presente un virtualenv Python **materializzato nella root del
repo** (`bin/`, `include/`, `lib/`, `lib64/`, `pyvenv.cfg`, `__pycache__/`). Questi non sono
tracciati da git (esclusi via `.gitignore`) ma occupano la root — da ignorare quando si esplora il
codice sorgente reale, che vive in `services/`, `web/`, e nei moduli root `config.py`/`models.py`/
`main.py`.

## Cosa manca (assente dal repo)

- Nessun test automatizzato (no `pytest`, no cartella `tests/`)
- Nessuna CI/CD (`.github/workflows/` non esiste)
- Nessun `LICENSE`
