# Stack tecnologico e setup

## Linguaggio

Python 3.12.3 (README richiede minimo 3.10+). Nessun altro linguaggio nel repo.

## Dipendenze (`requirements.txt`)

```
textual>=0.50.0               # framework TUI (Terminal User Interface)
httpx>=0.27.0                 # client HTTP asincrono per le chiamate API YGOPRODeck
pydantic>=2.0.0               # validazione dati / modelli tipizzati
opencv-python-headless>=4.9.0 # CV deterministica per il modulo di Grading (no GUI/GTK)
numpy>=1.26.0                 # usato da opencv-python-headless
ollama>=0.2.0                 # client ufficiale (AsyncClient) verso il server Ollama locale
```

Nessun database, nessun framework web/browser: tutta l'interfaccia è testuale via Textual, in
esecuzione in terminale.

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
- Se il container non è in esecuzione, il tab "Grading Carta" fallisce con un errore leggibile
  (`InspectorAgentError`, vedi [04-servizi.md](04-servizi.md)); le altre tab dell'app non ne
  risentono.

## Avvio del progetto

Da README (comandi scritti per Windows/PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python main.py
```

Equivalente su Linux/macOS:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Non esiste build step (no bundling, no compilazione, no `pyproject.toml`/`setup.py`). L'unico
entry point è `main.py`, che istanzia `YGOValuerApp` (da `ui/app.py`) e chiama `.run()`.

## Nota ambientale

Nella working directory locale è presente un virtualenv Python **materializzato nella root del
repo** (`bin/`, `include/`, `lib/`, `lib64/`, `pyvenv.cfg`, `__pycache__/`). Questi non sono
tracciati da git (esclusi via `.gitignore`) ma occupano la root — da ignorare quando si esplora il
codice sorgente reale, che vive in `services/`, `ui/`, e nei moduli root `config.py`/`models.py`/
`main.py`.

## Cosa manca (assente dal repo)

- Nessun test automatizzato (no `pytest`, no cartella `tests/`)
- Nessuna CI/CD (`.github/workflows/` non esiste)
- Nessun `Dockerfile`
- Nessun `LICENSE`
- Nessun `.env`/`.env.example` — l'app non richiede API key (l'API YGOPRODeck è pubblica e senza
  autenticazione)
