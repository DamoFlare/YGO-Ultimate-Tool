# Note, limiti noti e cose a cui fare attenzione

## Cronologia: da YGOPRODeck a CardTrader per i prezzi

L'app originariamente prendeva i prezzi da YGOPRODeck (`card_sets[].set_price` /
`card_prices[].cardmarket_price`). L'utente ha segnalato prezzi molto più alti del reale (es.
1.20€ mostrati vs 0.20€ visti su Cardtrader) — indagando, la documentazione YGOPRODeck non
specifica l'origine/aggiornamento di `set_price`, e `cardmarket_price` è documentato come "il
prezzo più basso tra tutte le versioni della carta" (non specifico alla stampa selezionata):
nessuno dei due era un prezzo di mercato affidabile.

Primo tentativo: un'API Cardmarket via RapidAPI (`cardmarket-api-tcg`, provider tcggo). Scartata
dopo verifica empirica diretta (chiamate reali autenticate): **non ha dati per Yu-Gi-Oh!** (né
per Magic/One Piece), solo Pokémon e Lorcana. Tutti i riferimenti a RapidAPI sono stati rimossi
dal progetto (config, `.env`, permessi locali, eventuale server MCP).

Adottata **CardTrader** (marketplace reale, non un aggregatore) come unica fonte di prezzo.
YGOPRODeck resta nel progetto ma **solo per la ricerca/identificazione delle carte** — nessun suo
campo di prezzo viene più mostrato o usato in un calcolo. Dettagli completi in
[08-pricing-cardtrader.md](08-pricing-cardtrader.md).

## Cronologia: da JSON a SQLite per la collezione

Motivazione: `collection.json` veniva riscritto per intero (`json.dump`) a ogni salvataggio, senza
atomicità né lock — un crash a metà scrittura poteva corrompere il file. Finché la collezione era
solo consultiva il rischio era basso; con la feature di vendita in arrivo (vedi sezione
successiva) i dati diventano rilevanti anche economicamente, e serve inoltre un **id di riga
stabile** per poter agganciare in futuro tabelle relazionali (`listings`/`orders`) a uno specifico
stack di carte — cosa che una lista JSON senza id non permette.

Decisioni prese (discusse ed esplicitamente confermate dall'utente prima dell'implementazione):
- `pending_gradings.json` **resta invariato** (file JSON separato, embedda foto base64, nessun
  collegamento con la vendita — vedi [07-grading.md](07-grading.md)).
- Migrazione dai dati esistenti tramite **script manuale one-off**
  (`scripts/migrate_to_sqlite.py`), non automatica all'avvio dell'app — scelta deliberatamente per
  avere un checkpoint esplicito e controllabile invece di una conversione silenziosa.
- Solo `collection.json` → SQLite in scope; `collection.csv` resta un artefatto derivato,
  rigenerato ogni volta, non spostato in DB.

**Rischio tecnico identificato e risolto**: un'implementazione ingenua di `save_collection()` con
`DELETE` totale + re-`INSERT` di tutto avrebbe vanificato lo scopo stesso della migrazione,
riassegnando `AUTOINCREMENT` nuovi a ogni salvataggio (il metodo viene chiamato dopo quasi ogni
mutazione). Risolto con upsert-per-`row_id`-noto-poi-prune — dettaglio implementativo completo in
[04-servizi.md](04-servizi.md).

**Deliberatamente NON aggiunto**: un vincolo `UNIQUE` su `(id, set_code, rarity, grade)` nello
schema SQL. SQLite tratta i valori NULL come distinti in un indice UNIQUE, quindi non
applicherebbe correttamente "tutti gli stack non gradati si fondono tra loro" per `grade IS NULL`.
La logica di merge/identità resta interamente in `AppState.add_card_to_collection` (Python,
`web/state.py`), esattamente come con lo zero-vincoli di JSON — un vincolo DB qui sarebbe
comportamento nuovo mai testato, non un ripristino.

Vedi [03-modelli-dati.md](03-modelli-dati.md) (nuovo campo `row_id` su `CollectionItem`) e
[04-servizi.md](04-servizi.md) (schema, strategia di scrittura, script di migrazione) per i
dettagli. Piano di implementazione completo salvato anche in
`C:\Users\ferla\.claude\plans\cosmic-giggling-rain.md` (fuori repo, plan file di Claude Code).

## Vendita carte su CardTrader (bulk + singola)

Implementata nella sessione successiva alla migrazione SQLite sopra (stessa motivazione: il
`row_id` stabile esiste apposta per questo). Bulk e vendita di una singola carta condividono
**lo stesso flusso di staging/review** — pattern preso in prestito da `pending_gradings`
(lista piatta indicizzata per id, ogni riga azionabile indipendentemente), non dal cursore
one-at-a-time di Bulk Add: "vendi una carta" è semplicemente "metti in staging una riga sola".

**Design deciso con l'utente e rispettato nell'implementazione**:
1. **Blueprint risolto e persistito una volta sola** — `CollectionItem.cardtrader_blueprint_id`/
   `cardtrader_blueprint_image_url` (nuove colonne, migrazione additiva in
   `services/storage.py`). Mai ricalcolato dopo il primo match: a differenza del prezzo
   (`find_real_prices`, dove un match sbagliato è solo un numero storto), qui un match sbagliato
   deciderebbe quale carta fisica si promette di spedire. Se ambiguo, l'utente disambigua una
   volta scegliendo tra i candidati (con relativa immagine) e la scelta resta fissa.
2. **Condizione mai assunta**: il form di staging (`_sell_staging.html`) parte vuoto/obbligatorio
   per le carte non gradate; pre-compilato solo se la carta ha già un grade.
3. **Controllo visivo anti-mismatch**: ogni riga in staging mostra `image_url` del blueprint
   CardTrader risolto (o dei candidati, se ambiguo) prima di poter confermare.
4. **Idempotenza locale**: `StorageService.get_active_listing_for_row()` blocca sia il doppio
   staging sia la doppia creazione se esiste già un annuncio `active` per quello stack.
5. **Nessun webhook**: `POST /sell/poll-orders` è l'unico modo (manuale) per rilevare vendite,
   via `GET /orders`. Non tocca mai `CollectionItem.quantity` — riconciliare una vendita con la
   quantità posseduta resta un'operazione manuale (limite noto, non un bug).
6. **Lingua sempre scelta manualmente per riga, mai dedotta dal `set_code`**: l'utente ha
   segnalato che la sua collezione fisica è interamente in italiano, ma in fase di ricerca/
   aggiunta (`services/ygoprodeck_api.py`) l'API YGOPRODeck restituisce solo stampe in inglese —
   quindi `CollectionItem.set_code` (es. `RA01-EN001`) **non riflette la lingua reale della copia
   posseduta**. Persistere/dedurre una lingua da lì per la vendita sarebbe stato sbagliato quasi
   sempre per questa collezione. Soluzione: `SellStagingItem.language` è un campo select
   editabile per riga in `_sell_staging.html` (`config.CARDTRADER_SELL_LANGUAGES`, opzioni
   IT/EN/FR/DE/ES), pre-selezionato su `config.DEFAULT_SELL_LANGUAGE = "it"` ma sempre
   sovrascrivibile — non un default silenzioso indiscutibile. Passato a
   `create_listing(..., language=...)` e persistito su `Listing.language` (nuova colonna,
   migrazione additiva come le altre). Rischio più basso rispetto a blueprint/condizione: una
   lingua sbagliata non falsa quale carta fisica si vende, solo la lingua dichiarata — per questo,
   se il valore inviato non è tra quelli validi, si ripiega silenziosamente sul default invece di
   bloccare la riga (a differenza della condizione, che blocca sempre se mancante).
7. **Prezzo suggerito automatico**: quando si seleziona/pre-seleziona una condizione, il campo
   prezzo si auto-compila con `get_price_for_condition(condizione) * (1 - config.SELL_SUGGESTED_PRICE_DISCOUNT)`
   (default 10% di sconto, tunabile in `config.py`) — resta comunque liberamente modificabile,
   è solo un punto di partenza. Per carte già gradate il prezzo è pre-compilato lato server al
   momento dello staging (`web/routers/sell.py::sell_stage`); per condizione scelta manualmente
   l'aggiornamento avviene lato client in `web/static/sell.js` (delegazione eventi su
   `document.body`, non sui singoli `<select>`, perché `#sell-page-content` viene interamente
   ri-renderizzato da htmx dopo ogni azione — un listener sul singolo elemento andrebbe
   ri-agganciato a ogni swap, la delegazione lo evita). I prezzi suggeriti per tutte e 5 le
   condizioni sono incorporati per riga come `data-prices` (JSON) sul `<select>` della condizione,
   calcolati in `_sell_context()` — nessuna chiamata di rete al cambio condizione.

**Schema**: nuova tabella `listings` (`services/storage.py`) — `collection_row_id` (FK verso
`collection_items.row_id`, **non imposta a livello DB** perché l'app non attiva mai
`PRAGMA foreign_keys`; l'integrità è gestita proceduralmente: `/collection/delete`
(`web/routers/collection.py`) blocca la cancellazione di uno stack con un annuncio `active`).

**Bug reali scoperti durante il test dal vivo (POST /products), non deducibili dalla sola
documentazione**:
- L'id del prodotto creato è annidato in `response["resource"]["id"]`, non in un campo `id` di
  primo livello — la risposta reale è `{"result": "success"|"warning", "warnings": {...},
  "resource": {...}}`. `CardTraderAPI.create_listing()` ritorna `resource` già "spacchettato"
  proprio per non far trapelare questo envelope ai chiamanti.
- La property per la lingua **non** si chiama `language` ma `yugioh_language` — mandare
  `language` non dà errore, viene silenziosamente ignorata con un warning nella risposta
  (`"Not allowed property language has been ignored"`), che è più insidioso di un 422 perché il
  resto della richiesta va comunque a buon fine. `condition` invece è la chiave corretta così
  com'era stata assunta.
- Il probe iniziale (payload vuoto/incompleto su `POST /products`) ha confermato correttamente lo
  schema di primo livello (`blueprint_id`/`price`/`quantity` come campi piatti, `price` un numero
  semplice non annidato in `{cents, currency}`) — quella parte non ha richiesto correzioni.

**Verificato dal vivo end-to-end** (con conferma esplicita dell'utente per l'annuncio reale,
poi cancellato subito dopo): creazione di un annuncio reale su una carta di basso valore
(Neo-Spacian Glow Moss, STON-EN006), verifica via `GET /products/export`, cancellazione via
`DELETE /products/:id`, verifica che fosse sparito — round trip completo confermato funzionante
col fix sopra. Accesso Full API/seller del token confermato in precedenza (`GET /products/export`,
`GET /orders`, `GET /info` → 200 già prima di questa feature).

**Limiti noti espliciti** (non implementati in questa v1, per scelta):
- Nessuna riconciliazione automatica tra annuncio venduto e quantità posseduta in collezione.
- Idempotenza solo locale: se un annuncio viene cancellato a mano dal sito CardTrader, il record
  locale resta "attivo" finché non lo si cancella anche da qui (innocuo: blocca solo un
  ri-listing, nessun rischio di duplicato reale). Il rischio opposto — DB locale che perde un
  annuncio attivo mentre su CardTrader è ancora live — non è mitigato; richiederebbe incrociare
  `GET /products/export` col locale in `/sell/poll-orders`.
- `GET /orders` non è ancora stato osservato con un ordine reale — `sell_poll_orders`
  (`web/routers/sell.py`) estrae gli id prodotto venduti in modo difensivo da un paio di percorsi
  chiave plausibili; va rivisto alla prima vendita vera.
- Nessun tetto alla quantità in vendita rispetto a quella posseduta (solo un default, editabile
  liberamente).

File principali: `services/cardtrader_api.py` (`resolve_blueprint_for_sale`, `create_listing`,
`delete_listing`, `list_orders`), `services/storage.py` (tabella `listings` + CRUD),
`web/routers/sell.py` (tutte le route `/sell/*`), `web/state.py` (`SellStagingItem`,
in-memory, mai persistito — a differenza di `pending_gradings` è economico da ricostruire).

## Bug reale: prezzi gonfiati per filtro lingua sbagliato in `find_real_prices`

Scoperto dall'utente controllando a mano un prezzo (D.D. Assailant, SDDE-EN017): l'app mostrava
NM=3.51€/LP=4.30€ mentre CardTrader aveva inserzioni reali italiane da 0.19€. Causa: `lang` in
`CardTraderAPI.find_real_prices()` veniva dedotto dal `set_code` (es. "EN" da "SDDE-EN017") e
usato per filtrare le inserzioni di mercato per lingua — ma il `set_code` salvato è **sempre**
inglese (YGOPRODeck restituisce solo stampe inglesi in ricerca, vedi sopra "Lingua sempre scelta
manualmente"), quindi il calcolo prezzo guardava solo la manciata di inserzioni inglesi (poche,
care) invece delle inserzioni italiane reali (molte, economiche) — esattamente il prezzo che
l'utente vedeva davvero su CardTrader.

**Fix**: `lang` in `find_real_prices` ora usa direttamente `config.DEFAULT_SELL_LANGUAGE` ("it")
invece del token parsato dal `set_code` — stessa correzione concettuale già fatta lato vendita
(vedi sopra), estesa al lato lettura/pricing che era rimasto scoperto.

**Impatto reale misurato**: dopo il fix, refresh di tutta la collezione (172 carte) →
**135 carte (78%) con variazione di prezzo NM > 15%**, quasi sempre in discesa (prezzi
precedentemente gonfiati). Non un caso isolato: il bug toccava sistematicamente quasi ogni carta.

**Conseguenza sugli annunci reali già creati**: i 33 annunci attivi su CardTrader (creati
dall'utente prima di questo fix) avevano prezzi calcolati con la formula sbagliata — corretti
manualmente uno per uno via il nuovo metodo `CardTraderAPI.update_listing_price()`
(`PUT /products/:id`, schema confermato dal vivo con un probe su un annuncio reale prima
dell'uso in massa) subito dopo il fix (31 aggiornati, 2 già corretti per caso, 0 falliti).
Aggiunta anche una route/bottone permanente per rifarlo in futuro senza script ad-hoc:
`POST /sell/listings/sync-prices` (`web/routers/sell.py`) + bottone "💶 Sincronizza prezzi" in
`_sell_listings.html` — riallinea ogni annuncio attivo al prezzo suggerito corrente
(`get_price_for_condition(condizione) * (1 - SELL_SUGGESTED_PRICE_DISCOUNT)`), utile ogni volta
che i prezzi di collezione cambiano dopo che un annuncio è già stato creato (refresh prezzi,
altri bug fix futuri, ecc.) — un annuncio non segue automaticamente i prezzi della collezione,
è uno snapshot preso alla creazione.

## Cronologia: da TUI Textual a web app (FastAPI + htmx)

Il modulo di Grading (foto + overlay di analisi) ha esposto un limite di fondo della TUI: il
rendering di immagini da terminale (`textual-image`) ha causato **due bug non banali** in
sessione:
1. Sovrapposizione visiva tra il box di analisi e il box "Collega il grade" — causa reale: i
   contenitori con bordo (`.box_panel`) non avevano mai una `height` esplicita in CSS, quindi
   Textual li trattava come `1fr` (dividono lo spazio disponibile in parti uguali con i
   fratelli, non si adattano al contenuto). Con contenuti piccoli non si notava; aggiungendo la
   riga di immagini il box ha superato la sua "quota" e la sua coda veniva scritta sotto al box
   successivo. Diagnosticato misurando le `region` dei widget con `run_test()` a diverse
   dimensioni di terminale: il punto di rottura scalava esattamente con metà altezza schermo, non
   col contenuto — prova decisiva che non era un problema di misura ma di distribuzione spazio.
   Fix applicato (`height: auto` su `.box_panel`) e funzionante.
2. Subito dopo, un secondo bug: le immagini mostrate non venivano scalate per adattarsi al box —
   si vedeva solo una porzione ritagliata a risoluzione nativa (edge case di `textual-image` con
   assegnazione dinamica dell'immagine dopo il mount del widget, non risolvibile con un fix
   rapido lato nostro codice).

A quel punto l'utente ha deciso di ritirare la TUI e costruire un front-end web, accettando il
lavoro di ricostruzione in cambio di un rendering immagini affidabile (i browser gestiscono lo
scaling nativamente, senza bisogno di alcun protocollo grafico da terminale). Migrazione
eseguita nella stessa sessione: **tutta la logica di business (`services/`, `models.py`,
`config.py`) è stata riusata senza modifiche** — è stato ricostruito solo il livello di
controllo/presentazione, da `ui/app.py` + `ui/views/*.py` (Textual, rimossi) a `web/` (FastAPI +
Jinja2 + htmx). Vedi [02-architettura.md](02-architettura.md) e [05-ui.md](05-ui.md) per
l'architettura attuale.

## Limite architetturale: Grading e quantità in stack (`CollectionItem`)

`CollectionItem` rappresenta uno **stack** di N copie identiche (stesso id/set_code/rarity) con
un solo prezzo base — non singole carte fisiche. Il modulo di Grading giudica invece una copia
fisica specifica, il che è concettualmente in tensione col modello a stack.

**Soluzione adottata** (minima, reversibile, senza refactor esteso): le carte con un `grade`
impostato non vengono più unite ad altri stack con lo stesso id/set_code/rarity ma **grade
diverso** — la chiave di match in `AppState.add_card_to_collection` (`web/state.py`, porting
della vecchia `add_card_to_collection_logic` di `ui/app.py`) include anche il grade. Le carte non
gradate (`grade=None`, il caso normale per Aggiungi Carta / Bulk) continuano a comportarsi
esattamente come prima.

**Perché**: evitare un refactor esteso del modello dati (tracking per-copia fisica invece che
per-stack), che avrebbe richiesto rivedere storage, CSV export, bulk-add e collection_view, non
giustificato per gradare occasionalmente qualche carta di valore.

**Come applicarla**: se in futuro serve tracciare grade multipli per la stessa carta/set/rarità
in quantità > 1 (es. 3 copie gradate diversamente), questo comportamento già lo permette (si
creano stack separati); se invece serve un vero tracking per-copia su tutta la collezione, va
rivalutato il modello dati da zero.

## Dipendenza dal server Ollama locale

La pagina "🩺 Grading Carta" richiede il server Ollama attivo (`docker compose up -d`, vedi
[01-stack-e-setup.md](01-stack-e-setup.md)). Se non è in esecuzione, l'analisi fallisce con un
`InspectorAgentError` mostrato nel partial di risposta (non un crash) — le altre pagine dell'app
restano completamente funzionanti. Il primo avvio del container richiede il pull del modello
`llava` (alcuni GB): può richiedere qualche minuto la prima volta.

## Formula di grading tarabile

Le soglie CV (usura bordi, deviazione centratura), i pesi dei sotto-voti e il mapping
grade→condizione sono costanti nominate in `config.py`, pensate per essere tarate osservando
risultati reali (non sono state validate su un dataset di carte fisiche). Dettagli e razionale
in [07-grading.md](07-grading.md).

## Limite di scope dichiarato: nessun sotto-voto "Corners"

Il PSA/BGS reale usa 4 sotto-voti (Centering, Corners, Edges, Surface). Questo sistema ne
implementa solo 3: né l'agente geometrico né il prompt del VLM (che esplicitamente ignora bordi
e centratura) coprono il rilevamento di angoli consumati/arrotondati. È una limitazione nota,
non un bug — vedi [07-grading.md](07-grading.md) per come estenderlo in futuro.

## Dati di collezione committati in git

`collection.json` (~1700 righe) e `collection.csv` (~170 righe) sono descritti come file
"auto-generati" ma contengono dati reali di una collezione di test/sviluppo e sono committati
nel repository (non sono in `.gitignore`). Dopo la migrazione a SQLite (vedi sopra) questi due
file **non vengono più scritti da alcun flusso applicativo** — restano in git solo come
istantanea congelata al momento della migrazione, mentre il vero store attivo (`collection.db`)
è correttamente in `.gitignore`. L'inconsistenza "dati utente tracciati in git" preesisteva già
prima di questo step e non è stata risolta unilateralmente (richiederebbe una decisione esplicita
dell'utente, es. rimuovere `collection.json`/`.csv` dal tracking git ora che sono solo backup).

Trattamento diverso e deliberato per `pending_gradings.json` (l'inbox del modulo Grading, vedi
[07-grading.md](07-grading.md)): **è** in `.gitignore`, perché contiene foto delle carte in
base64 (centinaia di KB per carta) — committarlo avrebbe gonfiato il repository con dati binari
in un modo che `collection.json`/`.csv` (solo testo/numeri) non fanno. Nessuna incoerenza voluta
con la scelta sopra, solo una valutazione diversa caso per caso.

## Vincoli operativi importanti

- **Rate limit YGOPRODeck**: `config.API_RATE_LIMIT_DELAY = 0.05` (secondi). Il README avvisa
  esplicitamente di non abbassare questo valore per evitare ban IP. Va rispettato in qualsiasi
  nuova funzionalità che chiami l'API in loop (es. bulk add).
- **Rate limit CardTrader**: `config.CARDTRADER_RATE_LIMIT_DELAY = 0.1` (secondi), sotto il
  limite reale di 200 richieste/10s globali (10/s su `/marketplace/products`). Vedi
  [08-pricing-cardtrader.md](08-pricing-cardtrader.md).
- **Gestione segreti**: il progetto ha un file `.env` (git-ignored, `.env.example` come
  template) con `CARDTRADER_TOKEN`, caricato da `config.py` via `python-dotenv`. YGOPRODeck resta
  pubblico senza chiave; il modulo di Grading usa un VLM locale (Ollama) anch'esso senza chiave.

## Cosa manca strutturalmente

- Nessun test automatizzato "formale" (no `pytest`, no cartella `tests/`) — verifica fatta con
  script ad-hoc/`TestClient` durante lo sviluppo, non con una suite persistente nel repo.
- Nessuna CI/CD (`.github/workflows/` assente)
- Nessun `LICENSE`
- Gestione errori "silenziosa": `ygoprodeck_api.py`/`storage.py` usano `try/except` ampi con
  `print()` verso stdout, non eccezioni propagate né un modulo di logging strutturato. Il modulo
  di Grading (`services/grading/`) devia intenzionalmente da questa convenzione: solleva
  eccezioni tipizzate (`CardCropError`, `InspectorAgentError`) con messaggi comprensibili,
  catturate e mostrate nel partial di risposta da `web/routers/grading.py` — preferire questo
  pattern per nuovo codice.

## Convenzioni di codice osservate (per restare coerenti in modifiche future)

- Docstring descrittiva in testa a ogni modulo
- `snake_case` per funzioni/variabili, `PascalCase` per classi
- Type hints sistematici (`typing.List`, `Optional`, `Dict`)
- Modelli dati sempre via Pydantic `BaseModel` con default espliciti
- Codici condizione carta standardizzati a 2 lettere maiuscole (`NM`, `EX`, `GD`, `LP`, `PO`),
  usati coerentemente in `config.py`, `models.py` e nei template
- Testi/notifiche UI in italiano, commenti nel codice in inglese
- Ogni pagina web ha un template "pieno" + uno o più partial (prefisso `_`) riusati sia al primo
  caricamento sia come risposta agli endpoint richiamati da htmx — vedi
  [05-ui.md](05-ui.md).
