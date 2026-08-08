# Configurazione e modelli dati

## `config.py`

Costanti globali applicative:

- `YGOPRODECK_BASE_URL` — `https://db.ygoprodeck.com/api/v7/cardinfo.php`
- `API_RATE_LIMIT_DELAY = 0.05` (secondi) — delay tra chiamate YGOPRODeck per non superare ~20
  req/sec. **Il README avvisa esplicitamente di non abbassare questo valore per evitare ban IP.**
- `CARDTRADER_TOKEN`, `CARDTRADER_BASE_URL`, `CARDTRADER_YUGIOH_GAME_ID` (=4),
  `CARDTRADER_RATE_LIMIT_DELAY`, `CARDTRADER_CONDITION_MAP` — configurazione dell'unica fonte
  prezzi dell'app. Vedi [08-pricing-cardtrader.md](08-pricing-cardtrader.md) per il dettaglio.
- `CONDITION_MULTIPLIERS` — moltiplicatore di prezzo per condizione carta rispetto al prezzo NM,
  usato **solo come fallback** quando CardTrader non ha un'inserzione reale per quella specifica
  condizione (non più la fonte primaria dei prezzi):
  - `NM` (Near Mint): 1.00
  - `EX` (Excellent): 0.88
  - `GD` (Good): 0.725
  - `LP` (Light Played): 0.55
  - `PO` (Poor): 0.35
- `CONDITION_NAMES` — mapping codice condizione → nome leggibile
- Path di default per la persistenza: `collection.json`, `collection.csv`
- Costanti del modulo di Grading (Ollama, soglie CV, pesi, mapping grade→condizione): vedi
  [07-grading.md](07-grading.md), che le documenta nel dettaglio.

## `models.py` (Pydantic v2 `BaseModel`)

- **`CardSetInfo`** — `set_name`, `set_code`, `set_rarity`, `set_rarity_code`, `set_price` (campo
  parsato dall'API YGOPRODeck ma **mai più usato per calcolare un prezzo mostrato all'utente** —
  resta solo come dato grezzo del risultato di ricerca)
- **`CardPrices`** — `cardmarket_price`, `tcgplayer_price`, `ebay_price`, `amazon_price`,
  `coolstuffinc_price` (idem: parsati ma non più usati per il pricing reale, vedi
  [06-note-e-discrepanze.md](06-note-e-discrepanze.md) per la storia)
- **`CollectionItem`** — elemento persistito nella collezione utente:
  - `row_id` (`Optional[int]`, default `None`) — chiave primaria surrogata SQLite
    (`services/storage.py`), assegnata al primo salvataggio e poi stabile nel tempo (upsert, mai
    ricreata da zero). Non fa parte dell'identità di business (vedi sotto), pensata per essere il
    futuro target FK di una tabella `listings` (vendita CardTrader, non ancora implementata — vedi
    [06-note-e-discrepanze.md](06-note-e-discrepanze.md)).
  - campi: `id`/passcode, `name`, `set_code`, `set_name`, `rarity`, `base_price`, `quantity`,
    `added_at`
  - campi opzionali del modulo Grading (default `None`, retro-compatibili): `grade` (float 1-10),
    `condition` (bucket NM/EX/GD/LP/PO mappato dal grade), `grade_breakdown` (dict con i
    sotto-voti centering/edges/surface)
  - campi opzionali del pricing CardTrader (default `None`, retro-compatibili):
    `real_condition_prices` (dict `{"NM": 15.89, "EX": 12.4, ...}`, solo i bucket con inserzioni
    reali trovate) e `price_source` (`"cardtrader"` se trovato un match, altrimenti `None` — mai
    `"ygoprodeck"`, quella fonte è stata rimossa dal pricing)
  - campi opzionali della feature vendita (default `None`): `cardtrader_blueprint_id`/
    `cardtrader_blueprint_image_url` — a differenza di `real_condition_prices`/`price_source`
    (ricalcolati liberamente a ogni refresh, un match sbagliato è solo un prezzo storto), questi
    vengono risolti **una volta sola** e mai più ricalcolati: un match sbagliato qui deciderebbe
    quale carta fisica si promette di spedire a un compratore. Vedi
    [06-note-e-discrepanze.md](06-note-e-discrepanze.md).
  - metodo `get_price_for_condition(condition)` — **ritorna il prezzo reale da
    `real_condition_prices` se presente per quella condizione; altrimenti stima da `base_price *
    CONDITION_MULTIPLIERS[condition]`** (fallback, non più la via primaria)
  - property `condition_prices` — dizionario di tutti i prezzi per condizione (reali dove
    disponibili, stimati altrove)
  - property `total_nm_price` — `base_price * quantity`
  - property `effective_price` — prezzo alla condizione realmente gradata (`condition`), o il
    prezzo NM se la carta non è gradata (comportamento invariato per le carte non gradate)
  - property `total_effective_price` — `effective_price * quantity`
- **`CardSearchResult`** — risultato di ricerca dall'API:
  - `id`, `name`, `type`, `desc`, `race`, `attribute`
  - `card_sets: List[CardSetInfo]`
  - `card_prices: List[CardPrices]`
- **`GradingResult`** — output del modulo di Grading (`services/grading/grader.py`): misure
  grezze (`centering_ratio`, `edge_wear_pct`, `surface_details` dal VLM), i 3 sotto-voti
  (`centering_subgrade`, `edges_subgrade`, `surface_subgrade`), e il risultato finale
  (`final_grade`, `condition`). Vedi [07-grading.md](07-grading.md) per la formula completa.
- **`Listing`** — un annuncio di vendita CardTrader (persistito nella tabella `listings`, vedi
  [04-servizi.md](04-servizi.md)): `id` (PK SQLite), `collection_row_id` (riferimento a
  `CollectionItem.row_id`, non imposto a livello DB), `cardtrader_blueprint_id`,
  `cardtrader_product_id` (id assegnato da CardTrader alla creazione), `condition`, `language`
  (scelta manualmente per riga in fase di vendita, mai dedotta da `set_code` — vedi
  [06-note-e-discrepanze.md](06-note-e-discrepanze.md)), `price_eur`, `quantity`, `status`
  (`active`/`sold`/`cancelled`, `config.LISTING_STATUS_*`), `created_at`/`updated_at`/`sold_at`
  (timestamp ISO), `error_message`. Creare/cancellare un `Listing` non tocca mai
  `CollectionItem.quantity` — la riconciliazione resta manuale.

## Formati di persistenza

- **`collection.db`** (SQLite) — **fonte di verità attuale** della collezione, tabella
  `collection_items` (vedi [04-servizi.md](04-servizi.md) per schema e strategia di scrittura).
  In `.gitignore` (mai committato). Introdotta al posto di `collection.json` — vedi cronologia in
  [06-note-e-discrepanze.md](06-note-e-discrepanze.md).
- **`collection.json`** — **legacy**: non più letto/scritto dall'app in esecuzione. Resta sul
  disco solo come backup prodotto dalla migrazione una-tantum (`scripts/migrate_to_sqlite.py`) e
  resta committato in git con l'ultimo stato noto prima della migrazione (dati reali di
  test/sviluppo, ~1700 righe) — è uno snapshot congelato, non va più considerato aggiornato.
- **`collection.csv`** — export leggibile generato da `StorageService.export_to_csv()`, colonne:
  `id, name, set_code, set_name, rarity, grade, condition, quantity, base_price_NM, price_EX,
  price_GD, price_LP, price_PO, total_NM_value, total_effective_value, price_source`. Logica
  invariata dalla migrazione (dipende solo dal ricevere una `List[CollectionItem]`, non da come è
  stata prodotta).
- **`test_col.json` / `test_col.csv`** — file di esempio minimale (una sola carta: Dark Magician,
  set `RA01-EN001`, rarità Ultra Rare, prezzo base 2.5€, quantità 2), verosimilmente usati per
  test manuali rapidi durante lo sviluppo. Non collegati alla migrazione SQLite.

⚠️ Nota: `collection.json`/`collection.csv` sono ancora **committati in git** (non in
`.gitignore`), mentre il vero store attivo (`collection.db`) lo è — inconsistenza preesistente
alla migrazione (era già così quando l'unica fonte era `collection.json`), non risolta
unilateralmente in questo step. Da rivalutare se si decide di pulire il repository: oggi
`collection.json`/`.csv` in git sono solo uno snapshot storico, non più generato/aggiornato da
alcun flusso applicativo.
