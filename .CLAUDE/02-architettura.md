# Architettura

## Struttura cartelle (file tracciati da git)

```
YGO-Ultimate-Tool/
├── .gitignore
├── README.md
├── requirements.txt
├── config.py                   # costanti globali / configurazione
├── models.py                   # modelli dati Pydantic
├── main.py                     # entry point
├── collection.json             # dati collezione utente (persistenza reale)
├── collection.csv              # export CSV della collezione
├── test_col.json               # file di esempio minimale (1 carta)
├── test_col.csv                # export CSV corrispondente
├── services/
│   ├── ygoprodeck_api.py       # client HTTP asincrono verso YGOPRODeck API
│   ├── storage.py              # persistenza JSON/CSV
│   └── scanner.py              # placeholder OCR/Vision (WIP, risultato simulato)
└── ui/
    ├── __init__.py
    ├── app.py                  # App Textual principale, CSS incluso inline
    └── views/
        ├── __init__.py
        ├── collection_view.py  # tab "Collezione & Valutazione"
        ├── add_card_view.py    # tab "Aggiungi Carta"
        ├── bulk_add_view.py    # tab "Aggiunta Bulk" (non documentata nel README)
        └── scanner_view.py     # tab "Scan da Immagine (OCR/Vision)"
```

Non esistono `docs/`, `CONTRIBUTING.md`, `LICENSE`, `Makefile`, `.github/workflows/`, `tests/`,
`pyproject.toml`, `Dockerfile`.

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
6. **Scanner (WIP)**: `ScannerView` invoca `CardScannerService.scan_card_image()`, che ritorna
   sempre lo stesso risultato simulato (Dark Magician / RA01-EN001) se il file immagine esiste —
   nessun OCR/Vision reale è implementato.

## Concorrenza

Tutte le chiamate verso l'API esterna sono `async`/`await` (via `httpx.AsyncClient`), coerenti
con l'event loop nativo di Textual. Rate limiting manuale con `asyncio.sleep` per rispettare il
limite dell'API YGOPRODeck (vedi [04-servizi.md](04-servizi.md)).
