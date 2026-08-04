# Note, limiti noti e cose a cui fare attenzione

## Limite architetturale: Grading e quantità in stack (`CollectionItem`)

`CollectionItem` rappresenta uno **stack** di N copie identiche (stesso id/set_code/rarity) con
un solo prezzo base — non singole carte fisiche. Il modulo di Grading giudica invece una copia
fisica specifica, il che è concettualmente in tensione col modello a stack.

**Soluzione adottata** (minima, reversibile, senza refactor esteso): le carte con un `grade`
impostato non vengono più unite ad altri stack con lo stesso id/set_code/rarity ma **grade
diverso** — la chiave di match in `add_card_to_collection_logic` (`ui/app.py`) include anche il
grade. Le carte non gradate (`grade=None`, il caso normale per Aggiungi Carta / Bulk) continuano
a comportarsi esattamente come prima.

**Perché**: evitare un refactor esteso del modello dati (tracking per-copia fisica invece che
per-stack), che avrebbe richiesto rivedere storage, CSV export, bulk-add e collection_view, non
giustificato per gradare occasionalmente qualche carta di valore.

**Come applicarla**: se in futuro serve tracciare grade multipli per la stessa carta/set/rarità
in quantità > 1 (es. 3 copie gradate diversamente), questo comportamento già lo permette (si
creano stack separati); se invece serve un vero tracking per-copia su tutta la collezione, va
rivalutato il modello dati da zero.

## Dipendenza dal server Ollama locale

Il tab "🩺 Grading Carta" richiede il server Ollama attivo (`docker compose up -d`, vedi
[01-stack-e-setup.md](01-stack-e-setup.md)). Se non è in esecuzione, l'analisi fallisce con un
`InspectorAgentError` mostrato in UI (non un crash) — le altre tab dell'app restano
completamente funzionanti. Il primo avvio del container richiede il pull del modello `llava`
(alcuni GB): può richiedere qualche minuto la prima volta.

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

- **Rate limit API**: `config.API_RATE_LIMIT_DELAY = 0.05` (secondi). Il README avvisa
  esplicitamente di non abbassare questo valore per evitare ban IP dall'API YGOPRODeck. Va
  rispettato in qualsiasi nuova funzionalità che chiami l'API in loop (es. bulk add, refresh
  prezzi).
- Nessuna API key richiesta: l'API YGOPRODeck è pubblica e il modulo di Grading usa un VLM
  locale (Ollama) senza autenticazione. Il progetto non ha ancora bisogno di gestione segreta
  (`.env`); se in futuro si aggiungesse un provider esterno (es. un VLM cloud in alternativa a
  `llava`), andrebbe introdotta.

## Cosa manca strutturalmente

- Nessun test automatizzato, nessuna cartella `tests/`
- Nessuna CI/CD (`.github/workflows/` assente)
- Nessun `LICENSE`
- Gestione errori "silenziosa": `ygoprodeck_api.py`/`storage.py` usano `try/except` ampi con
  `print()` verso stdout, non eccezioni propagate né un modulo di logging strutturato. Il modulo
  di Grading (`services/grading/`) devia intenzionalmente da questa convenzione: solleva
  eccezioni tipizzate (`CardDetectionError`, `InspectorAgentError`) con messaggi comprensibili,
  catturate e mostrate in UI da `ui/app.py` — preferire questo pattern per nuovo codice.

## Convenzioni di codice osservate (per restare coerenti in modifiche future)

- Docstring descrittiva in testa a ogni modulo
- `snake_case` per funzioni/variabili, `PascalCase` per classi
- ID widget Textual in `snake_case` con prefissi semantici (`btn_`, `input_`, `#metric_`, ecc.)
- Type hints sistematici (`typing.List`, `Optional`, `Dict`)
- Modelli dati sempre via Pydantic `BaseModel` con default espliciti
- Codici condizione carta standardizzati a 2 lettere maiuscole (`NM`, `EX`, `GD`, `LP`, `PO`),
  usati coerentemente in `config.py`, `models.py` e nella UI
- Testi/notifiche UI in italiano, commenti nel codice in inglese
