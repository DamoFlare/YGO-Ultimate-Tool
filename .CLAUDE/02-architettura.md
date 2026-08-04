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
├── config.py                    # costanti globali / configurazione (incl. soglie grading)
├── models.py                    # modelli dati Pydantic (incl. GradingResult)
├── main.py                      # entry point
├── collection.json              # dati collezione utente (persistenza reale)
├── collection.csv               # export CSV della collezione
├── test_col.json                # file di esempio minimale (1 carta)
├── test_col.csv                 # export CSV corrispondente
├── services/
│   ├── ygoprodeck_api.py        # client HTTP asincrono verso YGOPRODeck API
│   ├── storage.py               # persistenza JSON/CSV
│   └── grading/
│       ├── __init__.py
│       ├── geometric_agent.py   # CV deterministica: normalizzazione, edge wear, centratura
│       ├── ai_agent.py          # client asincrono Ollama (VLM `llava`) per la superficie
│       └── grader.py            # orchestratore: unisce i due agenti nel grade finale 1-10
└── ui/
    ├── __init__.py
    ├── app.py                  # App Textual principale, CSS incluso inline
    └── views/
        ├── __init__.py
        ├── collection_view.py  # tab "Collezione & Valutazione"
        ├── add_card_view.py    # tab "Aggiungi Carta"
        ├── bulk_add_view.py    # tab "Aggiunta Bulk"
        └── grading_view.py     # tab "Grading Carta (CV + AI)"
```

Non esistono `docs/`, `CONTRIBUTING.md`, `LICENSE`, `Makefile`, `.github/workflows/`, `tests/`,
`pyproject.toml`.

Nota storica: il progetto è partito con un modulo scanner OCR/Vision placeholder
(`services/scanner.py` + `ui/views/scanner_view.py`) che ritornava sempre un risultato
simulato/hardcoded. È stato **sostituito interamente** dal modulo di Grading CV+VLM descritto
sopra (stesso tab riutilizzato, rinominato da "Scan da Immagine (OCR/Vision)" a "Grading Carta
(CV + AI)"). Se trovi riferimenti a `CardScannerService`/`ScannerView` altrove (vecchi commit,
appunti), sono superati.

## Livelli logici

Applicazione monolitica a 3 livelli:

1. **Config/dati** (root): `config.py`, `models.py` — costanti e modelli Pydantic condivisi.
2. **Servizi** (`services/`): logica esterna e persistenza — chiamate API, I/O su file.
3. **UI** (`ui/`): presentazione Textual — l'app e le 4 view/tab.

Nota architetturale importante: **una quantità significativa di logica di business vive dentro
`ui/app.py`** (classe `YGOValuerApp`) invece che nei services. Esempi: `refresh_all_prices`,
`perform_card_search`, `add_selected_card_to_collection`, `add_card_to_collection_logic`,
`perform_bulk_load`, `process_bulk_add_current`, `commit_bulk_collection`, `process_bulk_skip`,
`advance_bulk_queue`. I services (`ygoprodeck_api.py`, `storage.py`) restano più "puri"
(fetch dati / I/O), mentre l'orchestrazione e le regole applicative sono centralizzate nella App.

## Entry point e flusso di avvio

```
main.py
  └── from ui.app import YGOValuerApp
  └── YGOValuerApp().run()
```

`YGOValuerApp` (Textual `App`) al mount inizializza il client API (`YGOProDeckAPI`) e il
`StorageService`, carica la collezione da `collection.json` e popola la `collection_view`.

## Flusso dati principale

1. **Ricerca carta**: utente digita query in `AddCardView` → `YGOValuerApp.perform_card_search`
   → `YGOProDeckAPI.search_cards(query)` (cascata: passcode numerico → set code → fuzzy per nome)
   → risultati mostrati in due `OptionList` (carte / set-rarità disponibili).
2. **Aggiunta a collezione**: utente seleziona carta + condizione/quantità →
   `add_card_to_collection_logic` (in `ui/app.py`) crea/aggiorna un `CollectionItem` →
   `StorageService.save_collection()` scrive `collection.json` e rigenera `collection.csv`.
3. **Aggiunta bulk**: utente incolla N set-code in `BulkAddView` → `perform_bulk_load` risolve
   ogni codice via API in sequenza (rispettando il rate limit) → l'utente confema/scarta uno a
   uno (`process_bulk_add_current` / `process_bulk_skip` / `advance_bulk_queue`) → salvataggio
   finale con `commit_bulk_collection`.
4. **Refresh prezzi**: `refresh_all_prices` ri-interroga l'API per ogni carta già in collezione
   e aggiorna i prezzi base salvati.
5. **Visualizzazione/valutazione**: `CollectionView` legge la collezione in memoria, applica i
   moltiplicatori di `config.CONDITION_MULTIPLIERS` per condizione, mostra tabella con sorting
   e filtri, e metriche aggregate (carte uniche, pezzi totali, valore NM, stime EX/GD/LP/PO).
6. **Grading**: utente inserisce il path immagine in `GradingView` → `btn_analyze_card` →
   `YGOValuerApp.start_grading` lancia un Textual worker (`self.run_worker(...)`, con
   `grading_view.loading = True` per lo spinner nativo) → `CardGrader.grade_card()` esegue in
   sequenza l'agente geometrico (sync) e l'inspector VLM (async) → il risultato
   (`GradingResult`) viene mostrato in `GradingView`. Se l'utente collega il risultato a una
   carta (stesso motore di ricerca di `AddCardView`), `save_graded_card_to_collection` richiama
   `add_card_to_collection_logic` con `grade`/`condition` valorizzati. Dettagli completi in
   [07-grading.md](07-grading.md).

## Concorrenza

Tutte le chiamate verso le API esterne (YGOPRODeck, Ollama) sono `async`/`await` (via
`httpx.AsyncClient` e `ollama.AsyncClient`), coerenti con l'event loop nativo di Textual. Rate
limiting manuale con `asyncio.sleep` per rispettare il limite dell'API YGOPRODeck (vedi
[04-servizi.md](04-servizi.md)). La chiamata di grading (potenzialmente lenta, secondi/minuti su
CPU) gira in un Textual worker anziché in un semplice `await` diretto, per mantenere l'app
reattiva e mostrare uno stato di caricamento nativo.
