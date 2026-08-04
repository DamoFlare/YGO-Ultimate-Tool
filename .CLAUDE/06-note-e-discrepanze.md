# Note, WIP e discrepanze da tenere a mente

## Cose dichiaratamente incomplete (WIP)

- **Scanner OCR/Vision** (`services/scanner.py`, `ui/views/scanner_view.py`): il modulo esiste
  solo come placeholder architetturale. `scan_card_image()` ritorna sempre un risultato
  hardcoded (Dark Magician / RA01-EN001 / passcode 46986414), non fa alcun riconoscimento reale.
  La docstring specifica due possibili strade future: Multimodal LLM (GPT-4o, Claude 3.5 Sonnet,
  Gemini 1.5 Flash) oppure OCR locale (`easyocr`/`pytesseract`) con crop di bounding box. Nessuna
  di queste dipendenze è in `requirements.txt` oggi.

## Discrepanza README vs codice

Il README descrive solo 3 tab (Collezione & Valutazione, Aggiungi Carta, Scan da Immagine), ma
il codice ha una **quarta tab, "Aggiunta Bulk"** (`ui/views/bulk_add_view.py`), completamente
implementata e funzionante, non menzionata nel README. Anche l'albero directory nel README non
cita `bulk_add_view.py`, `test_col.json` né `test_col.csv`. Se si aggiorna il README, questa è la
prima cosa da correggere.

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
- Nessuna API key richiesta: l'API YGOPRODeck è pubblica. Se in futuro si integra un modulo
  vision/LLM per lo scanner, sarà necessario introdurre gestione segreta (es. `.env`), che oggi
  non esiste nel progetto.

## Cosa manca strutturalmente

- Nessun test automatizzato, nessuna cartella `tests/`
- Nessuna CI/CD (`.github/workflows/` assente)
- Nessun `LICENSE`
- Gestione errori "silenziosa": i services usano `try/except` ampi con `print()` verso stdout,
  non eccezioni propagate né un modulo di logging strutturato. Da tenere a mente se si vogliono
  migliorare l'osservabilità o il debug in produzione.

## Convenzioni di codice osservate (per restare coerenti in modifiche future)

- Docstring descrittiva in testa a ogni modulo
- `snake_case` per funzioni/variabili, `PascalCase` per classi
- ID widget Textual in `snake_case` con prefissi semantici (`btn_`, `input_`, `#metric_`, ecc.)
- Type hints sistematici (`typing.List`, `Optional`, `Dict`)
- Modelli dati sempre via Pydantic `BaseModel` con default espliciti
- Codici condizione carta standardizzati a 2 lettere maiuscole (`NM`, `EX`, `GD`, `LP`, `PO`),
  usati coerentemente in `config.py`, `models.py` e nella UI
- Testi/notifiche UI in italiano, commenti nel codice in inglese
