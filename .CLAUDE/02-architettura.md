# Architettura

## Struttura cartelle (file tracciati da git)

```
YGO-Ultimate-Tool/
├── .gitignore
├── README.md
├── requirements.txt
├── docker-compose.yml           # server Ollama self-hosted per il modulo Grading
├── docker/
│   ├── Dockerfile                # basato su ollama/ollama:latest
│   └── ollama-entrypoint.sh      # avvia il server e fa il pull di `llava` al primo avvio
├── config.py                    # costanti globali / configurazione (incl. WEB_HOST/PORT, soglie grading)
├── models.py                    # modelli dati Pydantic (incl. GradingResult)
├── main.py                      # entry point: avvia uvicorn su web.app:app
├── collection.json              # dati collezione utente (persistenza reale)
├── collection.csv               # export CSV della collezione
├── test_col.json                # file di esempio minimale (1 carta)
├── test_col.csv                 # export CSV corrispondente
├── .env                          # CARDTRADER_TOKEN (git-ignored, copiare da .env.example)
├── .env.example
├── services/
│   ├── ygoprodeck_api.py        # client HTTP asincrono verso YGOPRODeck API (solo ricerca carte)
│   ├── cardtrader_api.py        # client verso CardTrader (unica fonte prezzi, vedi 08-pricing-cardtrader.md)
│   ├── storage.py               # persistenza JSON/CSV
│   └── grading/
│       ├── __init__.py
│       ├── geometric_agent.py   # CV deterministica: normalizzazione, edge wear, centratura, overlay
│       ├── ai_agent.py          # client asincrono Ollama (VLM `llava`) per la superficie
│       └── grader.py            # orchestratore: unisce i due agenti nel grade finale 1-10 + immagini di debug
└── web/                         # applicazione FastAPI (livello di presentazione)
    ├── __init__.py
    ├── app.py                   # crea la FastAPI app, lifespan (init/chiusura AppState), monta i router
    ├── state.py                 # AppState condiviso: client API, collezione in memoria, code/flussi multi-step
    ├── deps.py                  # dependency injection FastAPI: templates Jinja2, accesso ad AppState
    ├── routers/
    │   ├── __init__.py
    │   ├── collection.py        # pagina Collezione: tabella, filtro/sort, refresh prezzi, delete, export CSV
    │   ├── add_card.py          # pagina Aggiungi Carta: ricerca, conferma
    │   ├── bulk_add.py          # pagina Aggiunta Bulk: coda, confirm/skip, salva tutto
    │   └── grading.py           # pagina Grading: upload, analisi, ricerca per collegare, salva
    ├── templates/                # HTML Jinja2: 4 pagine + partial per gli aggiornamenti htmx
    └── static/
        ├── htmx.min.js           # vendorizzato, non da CDN
        └── style.css             # CSS scritto a mano, tema scuro — nessun framework CSS
```

Non esistono `docs/`, `CONTRIBUTING.md`, `LICENSE`, `Makefile`, `.github/workflows/`, `tests/`,
`pyproject.toml`.

Nota storica: il progetto è passato per due architetture UI prima di quella attuale. Prima un
modulo scanner OCR/Vision placeholder (rimosso), poi una **TUI Textual completa** (4 tab, con
tutta la logica di business dentro `ui/app.py`) — anche questa **rimossa interamente**, ritirata
a favore dell'attuale web app perché il rendering di immagini da terminale (necessario per la
trasparenza del modulo di Grading) si è rivelato inaffidabile (due bug non banali di libreria in
sessione). Se trovi riferimenti a `ui/`, `YGOValuerApp`, `textual`/`textual-image` altrove
(vecchi commit, appunti), sono superati — vedi [06-note-e-discrepanze.md](06-note-e-discrepanze.md)
per la cronologia completa.

## Livelli logici

Applicazione a 3 livelli, ora più cleanly separati rispetto all'epoca della TUI:

1. **Config/dati** (root): `config.py`, `models.py` — costanti e modelli Pydantic condivisi.
2. **Servizi** (`services/`): logica esterna, persistenza, e — novità rispetto alla TUI — anche
   parte dell'orchestrazione applicativa (`AppState.add_card_to_collection` in `web/state.py` è
   il porting quasi 1:1 di quella che nella TUI era `add_card_to_collection_logic` dentro
   `ui/app.py`; qui vive in `web/` perché è comunque legata allo stato condiviso dell'app, non
   perché sia tornata ad essere "logica di presentazione").
3. **Web** (`web/`): router FastAPI (un file per pagina) + template Jinja2/htmx. Ogni handler è
   deliberatamente snello: legge input, chiama i servizi/`AppState`, renderizza un template.

## Entry point e stato condiviso

```
main.py
  └── uvicorn.run("web.app:app", host=config.WEB_HOST, port=config.WEB_PORT)
```

`web/app.py` usa il `lifespan` di FastAPI per creare un'istanza di `AppState` (in
`web/state.py`) all'avvio e chiuderla allo shutdown:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ygo = AppState()   # api, cardtrader, storage, grader, collection caricata da disco
    yield
    await app.state.ygo.close()  # chiude le sessioni httpx/Ollama
```

`AppState` è **un singolo stato globale in-memory per l'intero processo** — non ci sono sessioni
per-utente/per-browser-tab. È lo stesso modello mentale della vecchia TUI (un solo processo, un
solo stato), semplicemente spostato da attributi di una classe `App` Textual ad attributi di
questo oggetto condiviso via `request.app.state.ygo` (accessibile nei router tramite la
dependency `web.deps.get_state`). Limite noto e accettato, non un difetto di design mancato: vedi
[06-note-e-discrepanze.md](06-note-e-discrepanze.md).

## Flusso richieste principale

1. **Ricerca carta**: `POST /add/search` (form `query`) → `YGOProDeckAPI.search_cards(query)`
   (cascata: passcode numerico → set code → fuzzy per nome) → il template `_add_results.html`
   mostra ogni carta trovata **con tutte le sue stampe/set già elencate sotto** (nessun secondo
   giro di selezione lato server: ogni riga set porta già `card_id`+`set_code` in campi hidden
   del proprio form). **Nessun prezzo mostrato in questa fase**: YGOPRODeck qui serve solo a
   identificare la carta.
2. **Aggiunta a collezione**: `POST /add/confirm` (form `card_id`, `set_code`, `rarity`, `qty`)
   → ri-richiama `YGOProDeckAPI.get_card_by_id` (una chiamata extra, stateless per design) per
   recuperare l'oggetto carta completo → `AppState.add_card_to_collection()` chiama
   `CardTraderAPI.find_real_prices(set_code, rarity)` per il prezzo reale, crea/aggiorna un
   `CollectionItem` → il router salva su disco (`StorageService.save_collection`). Se CardTrader
   non trova un match, il prezzo resta `0.0` — mai un prezzo YGOPRODeck usato come stima.
3. **Aggiunta bulk**: `POST /bulk/load` (form `codes`) risolve ogni codice via YGOPRODeck e
   popola `AppState.bulk_queue`/`bulk_index`. `POST /bulk/confirm`/`POST /bulk/skip` avanzano la
   coda un passo alla volta (staged in memoria, non salvato su disco). `POST /bulk/save-all`
   persiste tutto insieme a fine coda — stessa semantica "conferma prima di salvare" della TUI.
4. **Refresh prezzi**: `POST /collection/refresh-prices` ri-interroga **solo CardTrader** per
   ogni carta in collezione e aggiorna `real_condition_prices`/`base_price`/`price_source`.
5. **Visualizzazione/valutazione**: `GET /` e `GET /collection/table` (quest'ultimo richiamato
   via htmx per filtro live/sort senza reload) leggono `AppState.collection`, chiamano
   `item.get_price_for_condition(cond)` per ogni condizione (prezzi reali CardTrader con
   fallback ai moltiplicatori di `config.CONDITION_MULTIPLIERS` solo dove manca un'inserzione
   attiva), calcolano le metriche aggregate, e renderizzano `_collection_content.html`.
6. **Grading**: `POST /grading/analyze` (upload multipart `image`) salva il file in un temp path,
   chiama `CardGrader.grade_card()` (che ritorna `(GradingResult, DebugImages)`), poi **cancella
   il file temporaneo** e incorpora le due immagini (`DebugImages.original`/`.annotated`) come
   PNG base64 direttamente nell'HTML di risposta (`web.state.image_to_data_uri`) — niente
   protocollo grafico da terminale, niente file da servire via una route statica. Il risultato
   resta in `AppState.last_grading_result`/`last_debug_images` (un solo slot) finché
   `POST /grading/save` non lo collega a una carta della collezione (stesso schema
   ricerca-e-conferma-stateless del punto 2). Dettagli completi in [07-grading.md](07-grading.md).

## Concorrenza

Tutte le chiamate verso le API esterne (YGOPRODeck, CardTrader, Ollama) sono `async`/`await`
(via `httpx.AsyncClient` e `ollama.AsyncClient`), e FastAPI/uvicorn girano su un event loop
asyncio — ogni handler di router è a sua volta `async def`. Rate limiting manuale con
`asyncio.sleep` per rispettare i limiti di YGOPRODeck e di CardTrader separatamente (vedi
[04-servizi.md](04-servizi.md) e [08-pricing-cardtrader.md](08-pricing-cardtrader.md)). La
chiamata di grading (potenzialmente lenta, secondi su CPU per l'inferenza Ollama) semplicemente
mantiene la richiesta HTTP aperta finché non risponde — niente worker/spinner lato server: la
UI mostra un indicatore di caricamento lato client (`hx-indicator` di htmx) per la durata della
richiesta.
