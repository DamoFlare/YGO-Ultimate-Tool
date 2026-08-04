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

## `services/grading/` — modulo di Grading Ibrido (CV + VLM locale)

Sostituisce interamente il vecchio placeholder `services/scanner.py`/`CardScannerService`
(rimosso). Implementazione reale, non un placeholder. Descrizione completa dell'architettura,
formula e soglie in [07-grading.md](07-grading.md); qui solo un riepilogo per orientarsi nel
codice.

- **`geometric_agent.py`** — zero dipendenze AI, solo `cv2`/`numpy`:
  - `normalize_card_image(path)` — rileva il contorno della carta (Canny + contorni, fallback su
    `minAreaRect` se non trova un quadrilatero pulito) e fa perspective warp verso un rettangolo
    canonico (`config.NORMALIZED_CARD_WIDTH/HEIGHT`). Solleva `CardDetectionError` se non trova
    proprio nessun contorno.
  - `calculate_edge_wear(img)` — % di pixel del perimetro sottile che si discostano (per colore)
    da un anello di riferimento più interno; ritorna una percentuale di "usura".
  - `calculate_centering(img)` — cerca il frame stampato interno e misura i margini rispetto ai
    bordi fisici della carta, ritornando i rapporti orizzontale/verticale (50/50 = perfetto) più
    un flag `detected` (se `False`, la misura non è affidabile e il chiamante deve usare un
    fallback prudente, non assumere centratura perfetta).
- **`ai_agent.py`** — `InspectorAgent`, client asincrono (`ollama.AsyncClient`) verso il server
  Ollama locale (`config.OLLAMA_BASE_URL`, modello `config.OLLAMA_VISION_MODEL = "llava"`).
  `analyze_surface(img)` invia l'immagine già normalizzata con `format="json"` e
  `temperature=0.1`, usando il system prompt fisso `config.INSPECTOR_SYSTEM_PROMPT` (schema:
  `has_scratches`, `scratch_severity`, `has_creases`, `crease_severity`, `details`). Solleva
  `InspectorAgentError` con messaggio comprensibile se il server non risponde o il JSON non è
  parsabile — **non** un traceback grezzo.
- **`grader.py`** — `CardGrader.grade_card(image_path)` orchestra i due agenti e produce un
  `GradingResult` (vedi [03-modelli-dati.md](03-modelli-dati.md)): esegue prima l'agente
  geometrico (sync), poi l'inspector VLM (async), calcola i 3 sotto-voti, il grade finale
  pesato/vincolato, e la condizione mappata.

Nessuna API key richiesta (il modello gira interamente in locale via Docker, vedi
[01-stack-e-setup.md](01-stack-e-setup.md)). Le dipendenze aggiunte (`opencv-python-headless`,
`numpy`, `ollama`) sono in `requirements.txt`.
