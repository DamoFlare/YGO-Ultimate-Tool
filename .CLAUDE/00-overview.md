# YGO Ultimate Tool — Panoramica

## Cos'è

Applicazione web locale (Python, FastAPI + HTML server-side con htmx) per gestire e valutare una
collezione di carte Yu-Gi-Oh! TCG. Nome descrittivo nel README: "Yu-Gi-Oh! TCG Valuer &
Collection Tracker". La cartella storica/di progetto era `YGO-TGC-Valuer/`.

Un server locale (`python main.py`) espone l'interfaccia sul browser a
`http://127.0.0.1:8000` — single-user, bindato solo su localhost, nessuna autenticazione (non
serve: nessuno oltre al proprietario della macchina può raggiungerlo). **Era originariamente una
TUI Textual**: è stata ritirata e ricostruita come web app perché il modulo di Grading aveva
bisogno di mostrare foto in modo affidabile, cosa che il rendering grafico da terminale non
garantiva (due bug non banali di libreria, vedi [06-note-e-discrepanze.md](06-note-e-discrepanze.md)).

Repository GitHub: `DamoFlare/YGO-Ultimate-Tool` (remote `origin`), branch unico `main`.

## Cosa fa (in breve)

1. Cerca carte (per nome, per passcode/ID numerico, o per set code tipo `RA01-EN001`) tramite
   l'API pubblica **YGOPRODeck** — usata solo per identificare la carta, mai per i prezzi.
2. Aggiunge le carte trovate a una collezione personale, con quantità e prezzo reale.
3. Calcola il valore della collezione usando **prezzi reali di mercato da CardTrader**
   (inserzioni live, non aggregati/storici) per ciascuna condizione (NM/EX/GD/LP/PO), con stima
   a moltiplicatore solo come fallback quando manca un'inserzione reale per quella condizione.
   Vedi [08-pricing-cardtrader.md](08-pricing-cardtrader.md).
4. Persiste la collezione su `collection.json` ed esporta in `collection.csv`.
5. Offre una modalità di inserimento massivo ("Aggiunta Bulk") per incollare molti set-code in
   una volta e confermarli uno a uno.
6. **Grada automaticamente** una carta fisica da una foto: un'architettura ibrida CV (OpenCV,
   deterministica) + VLM locale (Ollama/`llava`, self-hosted via Docker) calcola un grade 1-10
   stile PSA/BGS e lo mappa sulla condizione NM/EX/GD/LP/PO esistente. Vedi
   [07-grading.md](07-grading.md). Ha sostituito il precedente scanner OCR placeholder.

## Stato del progetto

- Repository giovane, sviluppato quasi interamente in un'unica lunga sessione: partito da 2
  commit iniziali (`First commit`, poi `Update .gitignore and add pyvenv configuration file`),
  poi TUI Textual → modulo di Grading (CV+VLM) → migrazione prezzi a CardTrader → **migrazione
  completa da TUI a web app** (FastAPI + htmx), tutte nella stessa sessione di lavoro.
- Nessun test automatizzato "formale" (no `pytest`/`tests/`), ma ogni feature è stata verificata
  end-to-end con chiamate reali ai servizi esterni (YGOPRODeck, CardTrader, Ollama) durante lo
  sviluppo. Nessuna CI/CD, nessuna licenza dichiarata.
- Il README descrive le 4 pagine (Collezione, Aggiungi Carta, Aggiunta Bulk, Grading Carta) come
  pagine web, non più tab di una TUI.
- Il modulo di Grading richiede un server Ollama locale in esecuzione (`docker compose up -d`,
  vedi [01-stack-e-setup.md](01-stack-e-setup.md)) — senza, la pagina Grading fallisce con un
  errore comprensibile ma le altre pagine funzionano normalmente.
- Il pricing richiede un token CardTrader valido in `.env` (`CARDTRADER_TOKEN`) — senza, la
  ricerca carte funziona comunque ma nessun prezzo viene mai mostrato (fallback silenzioso a
  `€0.00`). Vedi [08-pricing-cardtrader.md](08-pricing-cardtrader.md).

## Indice della knowledge base

- [01-stack-e-setup.md](01-stack-e-setup.md) — linguaggio, dipendenze, come avviare il progetto
  (Docker per Ollama, token CardTrader)
- [02-architettura.md](02-architettura.md) — struttura a livelli, entry point, flusso richieste
- [03-modelli-dati.md](03-modelli-dati.md) — `config.py`, `models.py`, formati JSON/CSV
- [04-servizi.md](04-servizi.md) — `services/` (API client di ricerca/prezzo, storage, grading)
- [05-ui.md](05-ui.md) — `web/` (FastAPI, router, template Jinja2/htmx)
- [06-note-e-discrepanze.md](06-note-e-discrepanze.md) — TODO impliciti, limiti noti, cronologia
  della migrazione dei prezzi e della migrazione da TUI a web
- [07-grading.md](07-grading.md) — architettura del modulo di Grading: formula, soglie, pesi,
  come tararli
- [08-pricing-cardtrader.md](08-pricing-cardtrader.md) — architettura del pricing CardTrader:
  matching, rate limit, limiti noti
