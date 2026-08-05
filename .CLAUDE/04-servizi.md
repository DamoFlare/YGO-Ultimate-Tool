# Servizi (`services/`)

## `services/ygoprodeck_api.py` — classe `YGOProDeckAPI` (solo ricerca carte, MAI prezzi)

Client HTTP asincrono (`httpx.AsyncClient`) verso l'API pubblica **YGOPRODeck**
(`https://db.ygoprodeck.com/api/v7/`). Nessuna autenticazione richiesta.

⚠️ **Usato esclusivamente per identificare le carte** (nome, passcode, set/rarità disponibili).
I campi di prezzo che questo client parsa (`CardSetInfo.set_price`, `CardPrices.*`) **non vengono
mai mostrati all'utente né usati per calcolare un prezzo**: la loro origine/aggiornamento non è
documentata da YGOPRODeck ed erano risultati molto distanti dai prezzi di mercato reali (vedi
[06-note-e-discrepanze.md](06-note-e-discrepanze.md)). L'unica fonte di prezzo è
`services/cardtrader_api.py` (sotto).

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
- `close()` — chiude la sessione httpx; chiamato dal `lifespan` di `web/app.py`
  (`await app.state.ygo.close()`) allo shutdown del server per evitare connessioni pendenti

## `services/cardtrader_api.py` — classe `CardTraderAPI` (unica fonte di prezzo)

Client HTTP asincrono verso l'API autenticata di **CardTrader**
(`https://api.cardtrader.com/api/v2`, Bearer token da `.env`/`config.CARDTRADER_TOKEN`).
Descrizione completa dell'architettura, formula di matching e limiti noti in
[08-pricing-cardtrader.md](08-pricing-cardtrader.md); qui solo un riepilogo:

- `find_real_prices(set_code, rarity)` — funzione principale: risolve il set_code YGOPRODeck
  (es. `LOB-001`) in un'espansione + carta CardTrader, interroga le inserzioni di mercato reali
  (`/marketplace/products`), e ritorna il prezzo minimo per ciascuna condizione NM/EX/GD/LP/PO
  che ha inserzioni attive. Ritorna `None` (mai un'eccezione) su qualsiasi fallimento — nessun
  match, nessuna inserzione, rete giù, token invalido — per non rompere mai il flusso di
  aggiunta/refresh della collezione.
- Cache in memoria per dati stabili (espansioni, blueprint per espansione), nessuna cache per le
  inserzioni di mercato (i prezzi cambiano in tempo reale).
- Rate limiting con lo stesso pattern di `YGOProDeckAPI._rate_limit` (`config.CARDTRADER_RATE_LIMIT_DELAY`).

## `services/storage.py` — classe `StorageService`

Persistenza locale su file, nessun database:

- `load_collection()` — legge `collection.json` e deserializza in lista di `CollectionItem`
- `save_collection()` — serializza (`model_dump()`) e scrive `collection.json`
- `export_to_csv()` — genera `collection.csv` con colonne dettagliate per ogni condizione
  (id, name, set_code, set_name, rarity, grade, condition, quantity, base_price_NM,
  price_EX/GD/LP/PO, total_NM_value, total_effective_value, price_source)

## `services/grading/` — modulo di Grading Ibrido (CV + VLM locale)

Sostituisce interamente il vecchio placeholder `services/scanner.py`/`CardScannerService`
(rimosso). Implementazione reale, non un placeholder. Descrizione completa dell'architettura,
formula e soglie in [07-grading.md](07-grading.md); qui solo un riepilogo per orientarsi nel
codice.

- **`geometric_agent.py`** — zero dipendenze AI, solo `cv2`/`numpy`. Dettagli e cronologia
  dell'indagine sulla precisione (crop, edge wear, centering) in
  [07-grading.md](07-grading.md); qui solo un riepilogo:
  - `normalize_card_image(path)` — rileva il contorno della carta con doppia strategia
    (`_foreground_contour`, segmentazione per saturazione HSV — primaria, robusta su sfondi con
    texture come il legno; `_largest_contour`, Canny + contorno più grande — fallback), valida il
    quadrilatero risultante (`_quad_is_plausible`, proporzioni/angoli) prima di fidarsi del
    perspective warp altrimenti usa `minAreaRect`, e produce un rettangolo canonico
    (`config.NORMALIZED_CARD_WIDTH/HEIGHT`). Solleva `CardDetectionError` se non trova proprio
    nessun contorno.
  - `calculate_edge_wear(img)` — % di pixel del perimetro sottile che si discostano (per colore)
    da un anello di riferimento più interno, calcolato **separatamente per ciascuno dei 4 lati**
    (non un unico riferimento per tutta la carta, per non confondere un gradiente di luce con
    usura reale); ritorna una percentuale di "usura". Calibrazione dell'offset in mm→pixel non
    ancora validata su foto reali (limite noto, vedi 07-grading.md).
  - `calculate_centering(img)` — cerca il frame stampato interno (contorno quadrilatero convesso,
    non a contatto coi bordi immagine, area in un range plausibile) e misura i margini rispetto ai
    bordi fisici della carta, ritornando i rapporti orizzontale/verticale (50/50 = perfetto) più
    un flag `detected` (se `False`, la misura non è affidabile e il chiamante deve usare un
    fallback prudente, non assumere centratura perfetta). Nella pratica `detected` è quasi sempre
    `False` — limite noto non ancora risolto, vedi 07-grading.md.
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
