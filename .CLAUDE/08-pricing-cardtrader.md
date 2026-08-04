# Pricing via CardTrader (unica fonte di prezzo dell'app)

`services/cardtrader_api.py` — sostituisce completamente il pricing basato su YGOPRODeck
(`card_sets[].set_price` / `card_prices[].cardmarket_price`), che era la causa originale del
problema che ha motivato questo lavoro: l'utente notava prezzi mostrati dall'app molto più alti
di quelli reali visti su Cardtrader/CardTrader (es. 1.20€ nell'app vs 0.20€ reale). YGOPRODeck
non documenta la fonte/aggiornamento esatto di quei campi — vedi
[06-note-e-discrepanze.md](06-note-e-discrepanze.md) per la cronologia completa (incluso il
tentativo scartato con un'API Cardmarket via RapidAPI, che non aveva dati Yu-Gi-Oh!).

## Perché CardTrader

API di marketplace reale (non un aggregatore/media storica): ogni prezzo restituito è
un'inserzione di vendita attiva di un venditore reale, con condizione, lingua e quantità
specifiche. Richiede un Bearer token (`.env` → `CARDTRADER_TOKEN`, vedi
[01-stack-e-setup.md](01-stack-e-setup.md)).

## Divisione dei ruoli: YGOPRODeck vs CardTrader

- **YGOPRODeck** (`services/ygoprodeck_api.py`): **solo ricerca/identificazione carte** (nome,
  passcode, elenco set/rarità disponibili). Nessun campo di prezzo che restituisce viene più
  mostrato all'utente o usato in un calcolo.
- **CardTrader** (`services/cardtrader_api.py`): **unica fonte di prezzo**. Se non trova un
  match, il prezzo resta sconosciuto (`0.0`) — non c'è fallback su YGOPRODeck.

Motivo della separazione: CardTrader **non espone un endpoint di ricerca carte per nome/passcode
attraverso tutte le espansioni** (solo `/blueprints/export?expansion_id=` per una singola
espansione alla volta — verificato dal vivo, `/blueprints/search` non esiste). Costruire un
motore di ricerca equivalente richiederebbe scaricare e indicizzare localmente tutti i blueprint
delle ~683 espansioni Yu-Gi-Oh (centinaia di chiamate una tantum) — scartato per ora, valutato
come possibile evoluzione futura se si vuole eliminare la dipendenza da YGOPRODeck del tutto.

## Catena di risoluzione (`CardTraderAPI.find_real_prices(set_code, rarity)`)

1. **`_parse_set_code(set_code)`** — regex `^([A-Za-z0-9]+)-([A-Za-z]{2})?(\w+)$` spezza es.
   `RA01-EN001` in `("RA01", "en", "001")`, o `LOB-001` (senza lingua) in `("LOB", "en", "001")`.
2. **Espansione**: `_get_expansions_by_code()` fa **una sola chiamata bulk** `GET /expansions`
   (l'API non filtra server-side per gioco), la filtra client-side su
   `game_id == config.CARDTRADER_YUGIOH_GAME_ID` (**4**, confermato via `GET /games`), cache in
   memoria `{CODE: expansion_id}` per tutta la sessione. Verificato che il campo `code` di
   CardTrader combacia (case-insensitive) col prefisso set YGOPRODeck su più set reali: `LOB`,
   `RA01`, `SDMM`, `MRD`, `LOD`, `MFC`.
3. **Blueprint (carta specifica)**: `_get_blueprints_for_expansion(expansion_id)` fa
   `GET /blueprints/export?expansion_id=`, cache in memoria per expansion_id. Si filtra per
   `fixed_properties.collector_number` (match esatto o con zeri iniziali normalizzati), poi si
   usa `rarity` (contains case-insensitive, in entrambe le direzioni) come discriminante se ci
   sono più candidati con lo stesso numero.
4. **Prezzi reali**: `GET /marketplace/products?blueprint_id=` ritorna le inserzioni attive
   (`price.cents`, `properties_hash.condition`, `properties_hash.yugioh_language`). Si filtra per
   lingua (dedotta dal set code); se nessuna inserzione in quella lingua, si usa l'intero set di
   inserzioni piuttosto che non ritornare nulla.
5. **Raggruppamento per condizione**: `config.CARDTRADER_CONDITION_MAP` mappa i 5 bucket
   dell'app sulle 6 condizioni CardTrader (`Mint`/`Near Mint` → **NM**, `Slightly Played` →
   **EX**, `Moderately Played` → **GD**, `Played` → **LP**, `Poor` → **PO**); per ogni bucket con
   almeno un'inserzione si prende il **prezzo minimo**. Il dict ritornato contiene solo i bucket
   con inserzioni reali trovate (mai valori inventati).

Qualsiasi eccezione in qualunque punto della catena (rete, token invalido, nessun match, nessuna
inserzione) viene catturata e la funzione ritorna `None` — **mai propagata**, per non rompere mai
il flusso di aggiunta/refresh della collezione in `ui/app.py`.

## Come i prezzi arrivano in `CollectionItem`

`ui/app.py`:
- `add_card_to_collection_logic` (chiamata da "Aggiungi Carta", "Aggiunta Bulk", salvataggio del
  Grading): `base_price` parte da `0.0`; se `find_real_prices` trova un match, imposta
  `real_condition_prices`, `price_source = "cardtrader"`, e `base_price = real_prices["NM"]` se
  presente.
- `refresh_all_prices`: stessa logica per ogni `CollectionItem` già in collezione; notifica
  finale col conteggio "prezzi reali trovati per X/Y carte".

`models.CollectionItem.get_price_for_condition(condition)` preferisce sempre
`real_condition_prices[condition]` se presente; altrimenti stima con
`base_price * CONDITION_MULTIPLIERS[condition]` — questo fallback ha senso solo quando esiste
comunque un prezzo NM reale ma quella specifica condizione non ha inserzioni attive in quel
momento (non quando la carta non ha alcun match CardTrader, nel qual caso `base_price` è `0.0` e
la stima è `0.0` per tutte le condizioni).

## Rate limiting

`config.CARDTRADER_RATE_LIMIT_DELAY = 0.1` secondi tra chiamate, stesso pattern
elapsed-time-based di `YGOProDeckAPI._rate_limit`. Limiti reali dichiarati da CardTrader: 200
richieste/10s globali, 10 richieste/s specificamente su `/marketplace/products` (l'endpoint più
chiamato da questo servizio).

## Limiti noti

- **Matching euristico**: funziona bene sui set standard testati, ma può fallire silenziosamente
  su promo/edizioni speciali con set code atipici (fallback automatico a nessun prezzo, mai un
  crash).
- **Nessuna cache delle inserzioni di mercato**: ogni lookup fa una chiamata live (i prezzi
  cambiano); `refresh_all_prices` su una collezione grande fa molte chiamate sequenziali — per
  centinaia di carte può richiedere qualche minuto, nessuna barra di progresso oltre alla
  notifica finale.
- **Nessuna ricerca carte via CardTrader**: vedi sezione "Divisione dei ruoli" sopra — YGOPRODeck
  resta necessario per questo, per scelta esplicita (non un limite tecnico da risolvere).
