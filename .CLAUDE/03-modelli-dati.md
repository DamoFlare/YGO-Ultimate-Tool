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
  - campi: `id`/passcode, `name`, `set_code`, `set_name`, `rarity`, `base_price`, `quantity`,
    `added_at`
  - campi opzionali del modulo Grading (default `None`, retro-compatibili): `grade` (float 1-10),
    `condition` (bucket NM/EX/GD/LP/PO mappato dal grade), `grade_breakdown` (dict con i
    sotto-voti centering/edges/surface)
  - campi opzionali del pricing CardTrader (default `None`, retro-compatibili):
    `real_condition_prices` (dict `{"NM": 15.89, "EX": 12.4, ...}`, solo i bucket con inserzioni
    reali trovate) e `price_source` (`"cardtrader"` se trovato un match, altrimenti `None` — mai
    `"ygoprodeck"`, quella fonte è stata rimossa dal pricing)
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

## Formati di persistenza

- **`collection.json`** — array di `CollectionItem` serializzati (`model_dump()`), è la fonte di
  verità della collezione. Nel repo attuale contiene dati reali di test/sviluppo (~1700 righe).
- **`collection.csv`** — export leggibile generato da `StorageService.export_to_csv()`, colonne:
  `id, name, set_code, set_name, rarity, grade, condition, quantity, base_price_NM, price_EX,
  price_GD, price_LP, price_PO, total_NM_value, total_effective_value, price_source`.
- **`test_col.json` / `test_col.csv`** — file di esempio minimale (una sola carta: Dark Magician,
  set `RA01-EN001`, rarità Ultra Rare, prezzo base 2.5€, quantità 2), verosimilmente usati per
  test manuali rapidi durante lo sviluppo.

⚠️ Nota: `collection.json`/`collection.csv` sono descritti come "auto-generati" ma sono
effettivamente **committati in git con dati reali** — nel workflow attuale non vengono trattati
come artefatti da escludere (non sono in `.gitignore`). Da tenere a mente se si decide di pulire
il repository o aggiungere dati di test diversi.
