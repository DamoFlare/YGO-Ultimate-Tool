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

**Metodi di vendita** (aggiunti per la feature vendita, vedi
[06-note-e-discrepanze.md](06-note-e-discrepanze.md) per design e bug reali scoperti dal vivo):
- `_resolve_blueprint_candidates(set_code, rarity)` — logica di matching estratta da
  `find_real_prices` (passi 1-3: parse → espansione → filtro collector_number/rarità), condivisa
  da entrambi i metodi pubblici, **non** cattura eccezioni (decide chi chiama).
- `resolve_blueprint_for_sale(set_code, rarity)` — a differenza di `find_real_prices` (che tollera
  "nessun match" e ritorna sempre `None` su errore), distingue esplicitamente
  `resolved`/`ambiguous`/`not_found`/`error` — la UI di vendita deve reagire diversamente a ognuno.
- `create_listing(blueprint_id, price_eur, quantity, condition_bucket, language="en")` —
  `POST /products`. **A differenza di `find_real_prices`, propaga gli errori**
  (`CardTraderAPIError`) invece di ingoiarli: un fallimento di vendita deve essere visibile.
  Corpo confermato dal vivo (probe + test reale con cancellazione immediata): `blueprint_id`/
  `price`/`quantity` campi piatti, `price` un numero semplice (non `{cents, currency}`). La
  property per la lingua è `yugioh_language`, **non** `language` (quest'ultima viene ignorata in
  silenzio con un warning, non rifiutata — bug reale trovato durante il test dal vivo). Il metodo
  ritorna `response["resource"]` già "spacchettato" (la risposta reale è
  `{"result": ..., "warnings": ..., "resource": {...}}`, con l'id del prodotto creato annidato lì
  dentro, non a livello radice).
- `update_listing_price(product_id, price_eur)` — `PUT /products/:id`, stesso schema di
  `create_listing` (`price` piatto), confermato dal vivo con un probe su un annuncio reale prima
  dell'uso in massa (vedi [06-note-e-discrepanze.md](06-note-e-discrepanze.md), bug prezzi
  gonfiati). Aggiorna il prezzo mantenendo lo stesso id prodotto (a differenza di
  cancella+ricrea). Usato da `POST /sell/listings/sync-prices` per riallineare gli annunci
  attivi quando il prezzo in collezione cambia dopo la creazione dell'annuncio.
- `delete_listing(product_id)` — `DELETE /products/:id`, un 404 è trattato come successo
  (annullamento idempotente).
- `list_orders()` — `GET /orders`. Forma della risposta **non ancora osservata con un ordine
  reale** (solo "200, lista vuota" verificato) — il chiamante (`web/routers/sell.py`) va scritto
  in modo difensivo e rivisto alla prima vendita vera.

## `services/storage.py` — classe `StorageService`

Persistenza locale su **SQLite** (`collection.db`, tabella `collection_items`, stdlib `sqlite3`
— nessuna nuova dipendenza). Migrato da `collection.json` puro file, vedi cronologia e motivazione
in [06-note-e-discrepanze.md](06-note-e-discrepanze.md). Le 3 firme pubbliche sono rimaste
identiche apposta, per non dover toccare nessun call site in `web/state.py`/`web/routers/*.py`:

- `load_collection()` — `SELECT *` sulla tabella, ordinato per `row_id` (ordine di inserimento);
  deserializza `grade_breakdown`/`real_condition_prices` da testo JSON a dict. Stesso contratto
  permissivo di prima: qualunque eccezione (DB corrotto, lock, ecc.) viene loggata con `print()` e
  ritorna `[]`, non propagata.
- `save_collection(collection)` — riceve **sempre la lista intera** corrente (stessa semantica di
  prima: "la lista in memoria è la fonte di verità, storage ne persiste uno snapshot"), ma
  **non** fa un `DELETE`+`INSERT` cieco di tutto: farebbe perdere la stabilità del `row_id` a ogni
  save (il metodo viene chiamato dopo quasi ogni mutazione — add, refresh-prices, delete,
  bulk-save-all, grading-link — e un `AUTOINCREMENT` riassegnato ogni volta rimescolerebbe gli id).
  Strategia usata: **upsert per `row_id` noto, poi prune** — per ogni item con `row_id` già
  assegnato fa `UPDATE ... WHERE row_id=?` (fallback difensivo a `INSERT` se l'update non tocca
  righe); per ogni item nuovo (`row_id is None`) fa `INSERT` e ripopola `item.row_id =
  cursor.lastrowid` (unica mutazione che il metodo fa sull'input, puramente additiva); infine
  cancella dalla tabella qualunque riga il cui `row_id` non è più presente nella lista data (questo
  è il meccanismo su cui si basa `/collection/delete`, che ricostruisce `state.collection` per
  filtro e poi richiama `save_collection`). Tutto in una singola transazione
  (`isolation_level=None` + `BEGIN`/`COMMIT`/`ROLLBACK` espliciti) — a differenza del vecchio
  `json.dump` diretto, un crash a metà scrittura ora non corrompe più i dati.
- `export_to_csv()` — **invariato**: genera `collection.csv` con colonne dettagliate per ogni
  condizione (id, name, set_code, set_name, rarity, grade, condition, quantity, base_price_NM,
  price_EX/GD/LP/PO, total_NM_value, total_effective_value, price_source). Dipende solo dal
  ricevere una `List[CollectionItem]`, non dal backend di storage.

`scripts/migrate_to_sqlite.py` — script one-off (mai eseguito automaticamente all'avvio) che
importa `collection.json` in `collection.db` la prima volta: a differenza di `load_collection()`
fallisce rumorosamente su qualunque problema (file mancante, JSON invalido, riga che non valida
come `CollectionItem`, `collection.db` già popolato) invece di degradare silenziosamente a lista
vuota. Non tocca/cancella mai `collection.json` (resta come backup).

**Tabella `listings`** (feature vendita, vedi [06-note-e-discrepanze.md](06-note-e-discrepanze.md)):
righe create/gestite da `load_listings()`, `get_active_listing_for_row()` (il controllo di
idempotenza usato da `web/routers/sell.py` prima di mettere in staging o creare un annuncio),
`create_listing()` (backfilla `Listing.id` da `lastrowid`, stesso pattern di
`save_collection()` col `row_id`), `update_listing()`. Nessuna `FOREIGN KEY` dichiarata verso
`collection_items.row_id` — l'app non attiva mai `PRAGMA foreign_keys`, quindi un vincolo
dichiarato ma non imposto sarebbe fuorviante; l'integrità è garantita proceduralmente dalla
guardia in `/collection/delete` (vedi [05-ui.md](05-ui.md)), non a livello DB.

## `services/grading/` — modulo di Grading Ibrido (CV + VLM locale)

Sostituisce interamente il vecchio placeholder `services/scanner.py`/`CardScannerService`
(rimosso). Implementazione reale, non un placeholder. Descrizione completa dell'architettura,
formula e soglie in [07-grading.md](07-grading.md); qui solo un riepilogo per orientarsi nel
codice.

- **`geometric_agent.py`** — zero dipendenze AI, solo `cv2`/`numpy`. Dettagli e cronologia
  dell'indagine sulla precisione (crop, edge wear, centering) in
  [07-grading.md](07-grading.md); qui solo un riepilogo:
  - `normalize_card_image(path, corners)` — **non rileva più nulla automaticamente**: fa
    perspective warp del quadrilatero passato da chi chiama (i 4 angoli scelti a mano dall'utente
    in `web/static/corner-picker.js`) verso un rettangolo canonico
    (`config.NORMALIZED_CARD_WIDTH/HEIGHT`). Quattro round di rilevamento automatico (Canny,
    segmentazione per saturazione HSV, validazione di forma, espansione del bordo) sono stati
    tentati e abbandonati nella stessa sessione — vedi cronologia in 07-grading.md. Solleva
    `CardCropError` (rinominata da `CardDetectionError` — il significato è cambiato) se l'immagine
    non si apre o se `corners` non ha esattamente 4 punti.
  - `calculate_edge_wear(img)` — % di pixel del perimetro sottile con luminosità sopra una
    **soglia assoluta di sbiancamento** (`config.CARD_GRAYSCALE_WHITENESS_THRESHOLD`), non più
    una distanza relativa da un anello di riferimento (versione precedente, abbandonata per un
    problema di calibrazione — vedi cronologia in 07-grading.md); ritorna una percentuale di
    "usura". Soglia verificata solo su carte in buono stato (percentuali vicine a 0 come atteso),
    non ancora su una carta con usura reale — limite noto, vedi 07-grading.md.
  - `calculate_corner_whitening(img)` — stessa soglia assoluta di `calculate_edge_wear`, applicata
    a una ROI 50×50px per ciascuno dei 4 angoli. Misura solo lo sbiancamento, non l'arrotondamento
    geometrico dell'angolo (perso per costruzione dal perspective warp) — vedi 07-grading.md.
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
