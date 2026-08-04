# YGO Ultimate Tool — Panoramica

## Cos'è

Applicazione a riga di comando con interfaccia grafica testuale (TUI), scritta in Python, per
gestire e valutare una collezione di carte Yu-Gi-Oh! TCG. Nome descrittivo nel README:
"Yu-Gi-Oh! TCG Valuer & Collection Tracker". La cartella storica/di progetto era `YGO-TGC-Valuer/`.

Repository GitHub: `DamoFlare/YGO-Ultimate-Tool` (remote `origin`), branch unico `main`.

## Cosa fa (in breve)

1. Cerca carte (per nome, per passcode/ID numerico, o per set code tipo `RA01-EN001`) tramite
   l'API pubblica **YGOPRODeck**.
2. Aggiunge le carte trovate a una collezione personale, con quantità e prezzo base.
3. Calcola il valore della collezione applicando moltiplicatori di prezzo per condizione
   (NM/EX/GD/LP/PO), basati sui prezzi Cardmarket restituiti dall'API.
4. Persiste la collezione su `collection.json` ed esporta in `collection.csv`.
5. Offre una modalità di inserimento massivo ("Aggiunta Bulk") per incollare molti set-code in
   una volta e confermarli uno a uno.
6. Ha un modulo scanner OCR/Vision **non ancora implementato** (placeholder con risposta
   simulata) pensato per riconoscere una carta da una foto.

## Stato del progetto

- Repository giovane: solo 2 commit (`First commit`, poi `Update .gitignore and add pyvenv
  configuration file`).
- Nessun test automatizzato, nessuna CI/CD, nessuna licenza dichiarata.
- Il README descrive 3 tab (Collezione, Aggiungi Carta, Scanner) ma il codice ne ha **4**: esiste
  anche "Aggiunta Bulk", non documentata nel README. Vedi [06-note-e-discrepanze.md](06-note-e-discrepanze.md).
- Lo scanner OCR/Vision è dichiaratamente **work in progress**: ritorna sempre un risultato
  finto/hardcoded.

## Indice della knowledge base

- [01-stack-e-setup.md](01-stack-e-setup.md) — linguaggio, dipendenze, come avviare il progetto
- [02-architettura.md](02-architettura.md) — struttura a livelli, entry point, flusso dati
- [03-modelli-dati.md](03-modelli-dati.md) — `config.py`, `models.py`, formati JSON/CSV
- [04-servizi.md](04-servizi.md) — `services/` (API client, storage, scanner)
- [05-ui.md](05-ui.md) — `ui/` (app Textual e le 4 view/tab)
- [06-note-e-discrepanze.md](06-note-e-discrepanze.md) — TODO impliciti, WIP, discrepanze
  README/codice, cose a cui fare attenzione
