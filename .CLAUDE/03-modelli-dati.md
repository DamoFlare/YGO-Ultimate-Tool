# Configurazione e modelli dati

## `config.py`

Costanti globali applicative:

- `API_BASE_URL` — `https://db.ygoprodeck.com/api/v7/cardinfo.php`
- `API_RATE_LIMIT_DELAY = 0.05` (secondi) — delay tra chiamate API per non superare ~20 req/sec.
  **Il README avvisa esplicitamente di non abbassare questo valore per evitare ban IP.**
- `CONDITION_MULTIPLIERS` — dizionario moltiplicatore di prezzo per condizione carta rispetto al
  prezzo base (Cardmarket, condizione Near Mint):
  - `NM` (Near Mint): 1.00
  - `EX` (Excellent): 0.88
  - `GD` (Good): 0.725
  - `LP` (Light Played): 0.55
  - `PO` (Poor): 0.35
- `CONDITION_NAMES` — mapping codice condizione → nome leggibile
- Path di default per la persistenza: `collection.json`, `collection.csv`

## `models.py` (Pydantic v2 `BaseModel`)

- **`CardSetInfo`** — `set_name`, `set_code`, `set_rarity`, `set_rarity_code`, `set_price`
- **`CardPrices`** — `cardmarket_price`, `tcgplayer_price`, `ebay_price`, `amazon_price`,
  `coolstuffinc_price`
- **`CollectionItem`** — elemento persistito nella collezione utente:
  - campi: `id`/passcode, `name`, `set_code`, `set_name`, `rarity`, `base_price`, `quantity`,
    `added_at`
  - metodo `get_price_for_condition(condition)` — applica `CONDITION_MULTIPLIERS`
  - property `condition_prices` — dizionario di tutti i prezzi per condizione
  - property `total_nm_price` — `base_price * quantity`
- **`CardSearchResult`** — risultato di ricerca dall'API:
  - `id`, `name`, `type`, `desc`, `race`, `attribute`
  - `card_sets: List[CardSetInfo]`
  - `card_prices: List[CardPrices]`

## Formati di persistenza

- **`collection.json`** — array di `CollectionItem` serializzati (`model_dump()`), è la fonte di
  verità della collezione. Nel repo attuale contiene dati reali di test/sviluppo (~1700 righe).
- **`collection.csv`** — export leggibile generato da `StorageService.export_to_csv()`, colonne:
  `id, name, set_code, set_name, rarity, quantity, base_price_NM, price_EX, price_GD, price_LP,
  price_PO, total_NM_value`.
- **`test_col.json` / `test_col.csv`** — file di esempio minimale (una sola carta: Dark Magician,
  set `RA01-EN001`, rarità Ultra Rare, prezzo base 2.5€, quantità 2), verosimilmente usati per
  test manuali rapidi durante lo sviluppo.

⚠️ Nota: `collection.json`/`collection.csv` sono descritti come "auto-generati" ma sono
effettivamente **committati in git con dati reali** — nel workflow attuale non vengono trattati
come artefatti da escludere (non sono in `.gitignore`). Da tenere a mente se si decide di pulire
il repository o aggiungere dati di test diversi.
