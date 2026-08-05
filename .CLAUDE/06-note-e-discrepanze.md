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
nel repository (non sono in `.gitignore`). Nel workflow attuale quindi git traccia anche lo stato
della collezione personale — utile saperlo prima di fare commit "puliti" di solo codice, o prima
di aggiungere `.gitignore` per questi file se in futuro si vuole separare dati utente da codice.

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
  eccezioni tipizzate (`CardDetectionError`, `InspectorAgentError`) con messaggi comprensibili,
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
