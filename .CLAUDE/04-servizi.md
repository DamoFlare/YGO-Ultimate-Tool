# Servizi (`services/`)

## `services/ygoprodeck_api.py` — classe `YGOProDeckAPI`

Client HTTP asincrono (`httpx.AsyncClient`) verso l'API pubblica **YGOPRODeck**
(`https://db.ygoprodeck.com/api/v7/`). Nessuna autenticazione richiesta.

- Rate limiting manuale: `_rate_limit()` con `asyncio.sleep(config.API_RATE_LIMIT_DELAY)` prima
  di ogni chiamata, per restare sotto ~20 richieste/secondo.
- `search_cards(query)` — logica di ricerca a cascata:
  1. se la query è **numerica**, tenta ricerca per passcode/ID esatto
  2. se contiene `-` (o `.` normalizzato in `-`), tenta di interpretarla come **set code**
     (es. `RA01-EN001`): risolve il prefisso del set tramite `get_all_sets()` (endpoint
     `cardsets.php`, risultato cachato in memoria), poi chiama `get_cards_by_set_name`
  3. fallback: ricerca **fuzzy per nome** tramite il parametro `fname` dell'API
- `get_card_by_id(id)` — ricerca diretta per passcode
- `get_cards_by_set_name(set_name)` — ricerca per nome set risolto
- `_parse_card_json(...)` — trasforma il JSON raw dell'API in `CardSearchResult` (vedi
  [03-modelli-dati.md](03-modelli-dati.md))
- `close()` — chiude la sessione httpx; chiamato da `YGOValuerApp.action_quit` all'uscita
  dell'app per evitare connessioni pendenti

## `services/storage.py` — classe `StorageService`

Persistenza locale su file, nessun database:

- `load_collection()` — legge `collection.json` e deserializza in lista di `CollectionItem`
- `save_collection()` — serializza (`model_dump()`) e scrive `collection.json`
- `export_to_csv()` — genera `collection.csv` con colonne dettagliate per ogni condizione
  (id, name, set_code, set_name, rarity, quantity, base_price_NM, price_EX/GD/LP/PO,
  total_NM_value)

## `services/scanner.py` — classe `CardScannerService` (⚠️ PLACEHOLDER / WIP)

**Non è un'implementazione funzionante.** Il metodo `scan_card_image()` ritorna sempre un
risultato **simulato/hardcoded** (carta "Dark Magician", set `RA01-EN001`, passcode `46986414`)
se il file immagine passato esiste su disco — non fa alcun riconoscimento reale dell'immagine.

La docstring della classe contiene una specifica per lo sviluppo futuro ("[SPECIFICATION FOR
FUTURE DEVELOPMENT]"), che descrive due approcci alternativi pianificati ma non implementati:

1. **Multimodal LLM** — invio dell'immagine a un modello vision (GPT-4o, Claude 3.5 Sonnet,
   Gemini 1.5 Flash) per estrarre nome carta e set code direttamente.
2. **OCR locale** — uso di `easyocr` o `pytesseract` con crop delle bounding box specifiche
   (area titolo carta, area codice set) prima del riconoscimento testo.

Nessuna delle due dipendenze (`easyocr`, `pytesseract`, SDK di modelli vision) è attualmente in
`requirements.txt`. Se in futuro si implementa questo modulo, andrà aggiornato anche
`requirements.txt` e (se si scelgono LLM esterni) probabilmente introdotta gestione API key
(`.env`), oggi assente dal progetto.
