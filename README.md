# 🎴 Yu-Gi-Oh! TCG Valuer & Collection Tracker (TUI)

Benvenuto in **Yu-Gi-Oh! TCG Valuer & Collection Tracker**, un'applicazione CLI avanzata con interfaccia grafica da terminale (**TUI**) sviluppata in Python. Questo strumento ti permette di gestire la tua collezione di carte di Yu-Gi-Oh!, cercarle in tempo reale tramite le API ufficiali di **YGOPRODeck**, e valutarne istantaneamente il prezzo di mercato (**Cardmarket**) applicando moltiplicatori precisi basati sulle condizioni reali della carta.

---

## ✨ Caratteristiche Principali

1. **Ricerca Avanzata & Normalizzazione (Modulo 1)**:
   - Inserisci il nome della carta in **italiano** o **inglese** (con supporto fuzzy/completamento automatico). L'applicazione interroga l'API e restituisce i nomi ufficiali normalizzati in inglese.
   - Supporto per l'inserimento diretto tramite **Codice del Set** (es. `RA01-EN001` o `LOB-001`) o tramite **Passcode (ID della carta)**.
2. **Valutazione e Condizioni Cardmarket (Modulo 2)**:
   - Recupera istantaneamente il prezzo di listino di **Cardmarket** e **TCGPlayer**.
   - Mappatura automatica dei prezzi in base alle condizioni della carta secondo gli standard ufficiali Cardmarket:
     - **NM** (Near Mint) -> `100%` del prezzo di riferimento
     - **EX** (Excellent) -> `88%` del prezzo base
     - **GD** (Good) -> `72.5%` del prezzo base
     - **LP** (Light Played / Played) -> `55%` del prezzo base
     - **PO** (Poor) -> `35%` del prezzo base
   - Calcolo automatico in tempo reale del valore complessivo del Portfolio della Collezione sia per la condizione NM che per le stime delle altre condizioni.
3. **Persistenza e CSV Export**:
   - Salvataggio automatico dei dati in formato JSON (`collection.json`).
   - Esportazione professionale in formato CSV (`collection.csv`) con colonne dettagliate per ogni condizione.
4. **Architettura Modulare Vision / OCR (Modulo 3 - WIP)**:
   - Struttura pronta ed espandibile tramite `CardScannerService` e `ScannerView` per integrare fotocamere o caricamento di immagini per l'estrazione automatica di codici set tramite AI Vision (GPT-4o, Claude 3.5, Gemini) o OCR locale.
5. **Rate Limiting integrato**:
   - Gestione asincrona dei limiti API di YGOPRODeck (ritardo controllato di `0.05s` tra le richieste) per non incorrere nel blocco delle 20 req/sec.

---

## 🛠 Requisiti di Sistema & Installazione

L'applicazione è configurata per girare interamente in un ambiente virtuale isolato (`.venv`) usando **Python 3.10 o superiore**.

### 1. Clona/Accedi alla cartella del progetto
```bash
cd c:\Users\ferla\Desktop\YGO-TGC-Valuer
```

### 2. Configura l'ambiente virtuale e installa le dipendenze
Se non l'hai ancora fatto, puoi creare l'ambiente ed installare i pacchetti tramite i seguenti comandi:

```powershell
# Crea l'ambiente virtuale
python -m venv .venv

# Installa le dipendenze richieste (textual, httpx, pydantic)
.\.venv\Scripts\python -m pip install -r requirements.txt
```

---

## 🚀 Come Usare l'Applicazione (Guida all'Uso)

### Avvia l'applicazione:
```powershell
.\.venv\Scripts\python main.py
```

### Navigazione e Interfaccia TUI:
L'interfaccia si divide in 3 tab principali navigabili cliccando sui titoli con il mouse o usando la tastiera:

#### 1. Scheda 📋 `Collezione & Valutazione`
Questa è la dashboard principale in cui viene mostrato il tuo portfolio.
- **Tabella delle Carte**: Elenca tutte le tue carte salvate indicando passcode ID, Nome, Codice Set, Rarità, Quantità, Prezzo NM e le stime per tutte le condizioni inferiori (EX, GD, LP, PO).
- **Barra delle Metriche**: Mostra in alto il numero di carte uniche, i pezzi totali e il valore totale in NM ed euro.
- **Barra dei Moltiplicatori**: Visualizza all'istante la stima del valore totale se l'intera collezione fosse in condizione Excellent, Good, Light Played o Poor.
- **Filtro in Tempo Reale**: Digita del testo nella barra di ricerca (`Filtra collezione...`) per cercare istantaneamente carte all'interno della tua lista locale per nome o codice set.
- **Aggiorna Prezzi (🔄)**: Esegue una scansione in background delle carte in collezione per scaricare le quotazioni di Cardmarket più aggiornate.
- **Esporta CSV (📥)**: Salva un report professionale dettagliato nel file `collection.csv`.
- **Elimina Selezionata (🗑️)**: Clicca su una riga della tabella e premi il pulsante o usa la tastiera per rimuovere definitivamente una carta dal database.

#### 2. Scheda ➕ `Aggiungi Carta`
Il pannello dedicato all'inserimento e alla normalizzazione.
- **Ricerca**: Digita un termine di ricerca nella barra superiore. Puoi inserire:
  - Il nome in italiano (es. `Mago Nero`, `Drago Bianco Occhi Blu`).
  - Il nome in inglese (es. `Dark Magician`).
  - Un codice set specifico (es. `RA01-EN001`).
  - Un ID numerico passcode (es. `46986414`).
- **Selezione Carta**: Una volta cliccato su `Cerca`, la colonna di sinistra `Carte Trovate` mostrerà tutte le corrispondenze trovate nel database YGOPRODeck. Seleziona la carta desiderata.
- **Selezione Versione / Rarità**: Nella colonna di destra `Seleziona Set / Versione / Rarità` appariranno tutte le edizioni storiche e le stampe di quella carta con la relativa rarità e il rispettivo prezzo di mercato di Cardmarket. Seleziona l'edizione esatta in tuo possesso!
- **Conferma e Aggiunta**: Specifica la quantità desiderata (es. `3`) e clicca su `Aggiungi alla Collezione`. Riceverai una notifica di conferma e la carta verrà salvata istantaneamente nel database `collection.json`, aggiornando la tua collezione.

#### 3. Scheda 📷 `Scan da Immagine (OCR/Vision)`
La sezione dedicata all'architettura pronta per il futuro scanner fotografico.
- Puoi inserire il percorso di un file immagine locale (es. `C:\carte\dark_magician.jpg`) e premere `Analizza Immagine`.
- L'app simulerà l'analisi architetturale dell'immagine, estraendo i metadati pronti per essere passati al modulo di ricerca principale.

---

## 📁 Struttura della directory del codice

```text
YGO-TGC-Valuer/
│
├── .venv/                  # Ambiente virtuale Python
├── config.py               # Configurazione, moltiplicatori condizioni e costanti
├── models.py               # Data class Pydantic (Card, Prices, CollectionItem)
├── main.py                 # File di avvio del programma TUI
├── requirements.txt        # Dipendenze esterne
├── collection.json         # File di salvataggio locale della collezione (auto-generato)
├── collection.csv          # Esportazione in formato foglio di calcolo (auto-generato)
│
├── services/
│   ├── ygoprodeck_api.py   # Client asincrono HTTP per interrogare YGOPRODeck API
│   ├── storage.py          # Logica di persistenza per file JSON e CSV
│   └── scanner.py          # Modulo placeholder predisposto per OCR/Vision AI
│
└── ui/
    ├── app.py              # Classe principale e design CSS della Textual App
    └── views/
        ├── collection_view.py # Tabella della collezione e statistiche
        ├── add_card_view.py   # Logica di ricerca, autocomplete e form d'aggiunta
        └── scanner_view.py    # Interfaccia grafica placeholder per OCR
```

---

## 🔒 Rate Limiting e Buone Pratiche
L'applicazione rispetta le linee guida per sviluppatori di YGOPRODeck. Tra ogni richiesta viene inserita una pausa asincrona di `0.05` secondi. Non modificare questo valore per evitare di incorrere in ban temporanei del tuo indirizzo IP.
