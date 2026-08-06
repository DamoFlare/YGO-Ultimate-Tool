# Modulo di Grading (CV deterministica + VLM locale)

Architettura ibrida a 2 agenti + orchestratore, in `services/grading/`. Sostituisce interamente
il vecchio scanner OCR placeholder. Obiettivo: dato un percorso a una foto di una carta fisica,
calcolare un grade 1-10 stile PSA/BGS e mapparlo sulla scala di condizione NM/EX/GD/LP/PO già
usata per il pricing (`config.CONDITION_MULTIPLIERS`).

## Perché ibrido (CV + VLM) e non solo pixel-diffing

Un confronto 1:1 con una carta "Mint" di riferimento è stato scartato in fase di design perché
rumore ambientale, illuminazione e centratura di stampa generano troppi falsi positivi. Si separa
invece:
- **Difetti geometrici misurabili** (usura bordi, centratura) → CV deterministica, niente AI,
  risultati riproducibili.
- **Difetti di superficie che richiedono giudizio visivo** (graffi, pieghe) → VLM locale, perché
  non sono facilmente esprimibili come soglie matematiche su pixel.

## Pipeline (`services/grading/grader.py`, classe `CardGrader.grade_card()`)

1. `geometric_agent.normalize_card_image(path, corners)` — fa perspective warp del quadrilatero
   **fornito da chi chiama** (i 4 angoli della carta, in coordinate pixel della foto originale)
   verso un rettangolo canonico (`config.NORMALIZED_CARD_WIDTH/HEIGHT`, default 750x1047,
   proporzione fisica di una carta TCG 63x88mm). Solleva `CardCropError` se l'immagine non si apre
   o se `corners` non contiene esattamente 4 punti.
   **Il contorno non viene più rilevato automaticamente** — è l'utente che lo ritaglia a mano
   nella pagina web (`web/static/corner-picker.js`: trascina 4 maniglie sulla foto caricata,
   `POST /grading/analyze` riceve `corners` come stringa JSON insieme al file immagine). Più
   round di rilevamento automatico (Canny, segmentazione per saturazione HSV, validazione di
   forma, espansione del bordo) sono stati tentati e abbandonati nella stessa sessione — vedi
   "Cronologia: indagine precisione CV" più sotto per la storia completa di cosa non ha
   funzionato e perché si è passati al ritaglio manuale.
2. `geometric_agent.calculate_edge_wear(img)` — estrae la banda perimetrale sottile
   (`config.EDGE_WEAR_BORDER_PX`, default 5px, escludendo i primi `config.EDGE_WEAR_SKIN_PX`
   pixel più vicini al bordo del ritaglio) e calcola la % di pixel con luminosità (scala di grigi)
   sopra `config.CARD_GRAYSCALE_WHITENESS_THRESHOLD` (default 180/255) — **soglia assoluta sullo
   sbiancamento**, non più una distanza relativa da un anello di riferimento (vedi "Cronologia"
   sotto per perché quest'ultima è stata abbandonata). Ritorna una tupla `(pct, damaged_mask)`:
   `damaged_mask` è una maschera booleana (h,w) con esattamente i pixel segnalati come sbiancati,
   usata per l'overlay visivo (vedi sezione "Trasparenza" sotto).
3. `geometric_agent.calculate_corner_whitening(img)` — stessa logica a soglia assoluta di
   `calculate_edge_wear`, applicata a una ROI quadrata (`config.CORNER_ROI_PX`, default 50px) per
   ciascuno dei 4 angoli, inset dello stesso `EDGE_WEAR_SKIN_PX`. Misura solo lo **sbiancamento**
   (un difetto di colore che sopravvive al perspective warp), non l'**arrotondamento geometrico**
   dell'angolo — quello è un difetto di forma che il warp elimina per costruzione (forza qualunque
   punto rilevato vicino all'angolo a coincidere esattamente col vertice ideale del rettangolo di
   destinazione). Un eventuale rilevamento dell'arrotondamento andrebbe fatto sui punti del
   contorno **prima** del warp, non è implementato.
4. `geometric_agent.calculate_centering(img)` — cerca un contorno quadrilatero la cui area rientra
   in `config.CENTERING_FRAME_AREA_RATIO_RANGE` (default 0.55-0.95 dell'area totale della carta),
   **non tocca i bordi dell'immagine** (altrimenti è quasi certamente il bordo esterno della carta
   rilevato di nuovo, non il frame interno) ed è un **quadrilatero convesso** (`approxPolyDP` a 4
   punti + `cv2.isContourConvex`), e ne misura i margini rispetto ai bordi fisici, ritornando i
   rapporti orizzontale/verticale (50/50 = perfetto), un flag `detected`, e `bbox` (x,y,w,h del
   frame rilevato, `None` se non rilevato) — anche questo usato solo per l'overlay visivo, non per
   il calcolo del sotto-voto. **Nella pratica osservata (vedi cronologia sotto), `detected` è quasi
   sempre `False`**: il contorno del frame di stampa raramente soddisfa questi vincoli, quindi il
   sotto-voto centering scatta quasi sempre sul fallback prudente — limite noto, non ancora
   risolto.
5. `ai_agent.InspectorAgent.analyze_surface(img)` — invia l'immagine **già normalizzata** al
   modello `llava` via Ollama locale (`config.OLLAMA_BASE_URL`), con
   `config.INSPECTOR_SYSTEM_PROMPT` (fisso nello schema JSON — non modificarlo senza aggiornare
   anche il parsing in `ai_agent.py`; il contenuto testuale richiesto per `details` è invece
   liberamente modificabile), `format="json"`, `temperature=0.1`. Ritorna `has_scratches`,
   `scratch_severity`, `has_creases`, `crease_severity`, `details` (2-3 frasi che descrivono cosa
   è stato osservato, dove sulla carta, e il livello di confidenza — esteso da "1 frase" per dare
   più contesto nella UI).

## Calcolo dei sotto-voti (1-10)

- **Centering**: se `centering["detected"]` è `True`, si calcola la deviazione peggiore
  `max(|horizontal-50|, |vertical-50|)` e si guarda in `config.CENTERING_DEVIATION_TO_SUBGRADE`
  (lista ordinata di soglie ascendenti `(deviazione_max, subgrade)`, es. ≤2%→10, ≤5%→9, ...); oltre
  l'ultima soglia si usa `config.CENTERING_MIN_SUBGRADE`. Se `detected` è `False` (frame non
  rilevato con confidenza), si usa direttamente `config.CENTERING_FALLBACK_SUBGRADE` (default 7.0)
  invece di assumere una centratura perfetta.
- **Edges**: stesso schema a soglie ascendenti su `edge_wear_pct`, tabella
  `config.EDGE_WEAR_PCT_TO_SUBGRADE`, fallback `config.EDGE_WEAR_MIN_SUBGRADE`.
- **Corners**: stesso schema a soglie ascendenti su `corner_whitening_pct`, tabella
  `config.CORNER_WHITENESS_PCT_TO_SUBGRADE` (stessa forma della tabella Edges — stessa misura
  fisica, regione diversa), fallback `config.CORNER_MIN_SUBGRADE`.
- **Surface**: `config.SEVERITY_TO_SUBGRADE` mappa `"none"→10, "light"→7, "heavy"→3`; si prende il
  **minimo** tra il subgrade di `scratch_severity` e quello di `crease_severity` (un solo difetto
  serio abbassa comunque il voto di superficie). Stringa di severità inattesa dal VLM →
  `config.UNKNOWN_SEVERITY_FALLBACK_SUBGRADE` (7.0), per non premiare né penalizzare
  eccessivamente un output malformato.

## Grade finale

```
weighted_avg = centering_subgrade * 0.16 + edges_subgrade * 0.24 + corners_subgrade * 0.20 + surface_subgrade * 0.40
final_grade  = min(weighted_avg, min(centering_subgrade, edges_subgrade, corners_subgrade, surface_subgrade) + 1.0)
final_grade  = round(final_grade * 2) / 2   # arrotondato a step di 0.5
```

Pesi in `config.GRADE_SUBGRADE_WEIGHTS`. Il cap "peggior sotto-voto + 1.0" è una regola in stile
BGS: un singolo difetto grave non può essere "nascosto" da una media pesata favorevole. I pesi di
centering/edges/surface erano originariamente 20/30/50; quando è stato aggiunto corners sono
stati scalati proporzionalmente (×0.8) per fare spazio a corners=0.20, mantenendo il rapporto
relativo tra i tre invece di sceglierne uno nuovo a sensazione. Punto di partenza ragionevole,
**non validato su un dataset reale di carte**: da tarare osservando i risultati.

## Mapping grade → condizione di mercato

`config.GRADE_TO_CONDITION` (lista ordinata per soglia decrescente):

| Grade finale | Condizione |
|---|---|
| ≥ 8.5 | NM |
| ≥ 7.0 | EX |
| ≥ 5.5 | GD |
| ≥ 4.0 | LP |
| < 4.0 | PO (`config.GRADE_TO_CONDITION_FALLBACK`) |

Il risultato (`GradingResult.condition`) alimenta `CollectionItem.condition`, usato da
`CollectionItem.effective_price`/`total_effective_price` per mostrare il valore "reale" della
copia gradata accanto alla stima NM teorica in `CollectionView`.

## Come tarare la formula

Tutte le soglie/pesi sono costanti nominate in `config.py` (sezione "Grading Module" /
"Geometric Agent thresholds") — modificabili senza toccare la logica in `grader.py` o
`geometric_agent.py`. Se il grade percepito è sistematicamente troppo alto/basso rispetto a
carte fisiche note, il primo posto dove intervenire sono i pesi in
`config.GRADE_SUBGRADE_WEIGHTS` o le soglie `*_TO_SUBGRADE`.

## Trasparenza: immagini di debug e spiegazione del grade

Aggiunto dopo che l'utente ha chiesto di poter vedere la foto caricata, come viene ritagliata, e
capire perché si ottiene un certo grade (non solo i numeri nudi). Da quando il ritaglio è
manuale (vedi punto 12 della cronologia sotto), "come viene ritagliata" è mostrato **prima**
dell'analisi, non solo dopo: `web/static/corner-picker.js` disegna un poligono live sopra
l'anteprima della foto caricata mentre l'utente trascina i 4 angoli, quindi l'utente vede
esattamente quale quadrilatero sta per essere passato al perspective warp, non solo il risultato
finale. Durante il trascinamento appare anche una **lente d'ingrandimento** (`#cropper-magnifier`,
zoom 3x, tecnica CSS `background-position`/`background-size` — niente canvas) centrata sopra il
punto toccato (si sposta sotto se troppo vicina al margine superiore, per non finire tagliata
fuori dall'anteprima), con un mirino al centro, per piazzare l'angolo con precisione sub-pixel
senza che il cursore/dito coprano il punto esatto.

- `CardGrader.grade_card()` ritorna **una tupla** `(GradingResult, DebugImages)`, non solo
  `GradingResult` — attenzione se si aggiungono nuovi call site. `DebugImages` (dataclass in
  `grader.py`, non Pydantic — contiene `PIL.Image.Image`, non serializzabili e non persistite in
  `collection.json`) ha due campi:
  - `original` — la foto così com'è stata caricata, nessuna elaborazione.
  - `annotated` — l'immagine normalizzata (`normalize_card_image`) con overlay disegnati da
    `geometric_agent.build_annotated_image(normalized_img, damaged_mask, centering,
    corner_damaged_mask)`: rettangolo giallo sulla banda perimetrale controllata per l'usura,
    rettangoli arancioni sulle 4 ROI angoli controllate per lo sbiancamento, pixel rossi
    esattamente dove `damaged_mask`/`corner_damaged_mask` sono `True`, rettangolo ciano sul frame
    di centratura rilevato (`centering["bbox"]`, solo se `detected=True`). Una singola immagine
    risponde quindi sia a "come viene ritagliata/centrata" sia a "quali analisi vengono fatte".
- Mostrate nella pagina web (`web/routers/grading.py` + `templates/_grading_result.html`) come
  `<img src="data:image/png;base64,...">` — `web.state.image_to_data_uri(pil_image)` codifica
  ogni `PIL.Image` in PNG e la incorpora direttamente nell'HTML di risposta. Nessun file
  temporaneo da servire, nessun protocollo grafico, scaling gestito nativamente dal browser via
  CSS (`max-width: 100%` su `.grading-images img`).
- `GradingResult.explanation` (campo stringa) — spiegazione deterministica generata da
  `grader._build_explanation()`: identifica quale sotto-voto è il "collo di bottiglia" (il
  minimo dei tre, quello che determina il cap `peggiore + 1.0`) e compone 2-3 frasi in italiano
  che collegano numero→causa→effetto sul grade finale. Distinta dal testo libero del VLM
  (`surface_details["details"]`), mostrato separatamente come "Cosa ha visto l'AI".

Nota storica: la prima versione di questa sezione mostrava le immagini in una TUI Textual
tramite la libreria `textual-image`. Ha causato due bug di libreria non banali (sovrapposizione
di layout, poi immagini non scalate correttamente al box) — è stata la ragione diretta per cui
l'intera app è stata ricostruita come web app. Vedi
[06-note-e-discrepanze.md](06-note-e-discrepanze.md) per la cronologia completa. Il problema è
del tutto assente nell'implementazione web attuale: un `<img>` con `max-width: 100%` non ha
questi edge case.

## Cronologia: indagine precisione CV (crop, edge wear, centering)

L'utente ha segnalato che i grade calcolati sembravano poco precisi (es. una carta in condizioni
buone valutata 2.0/10 con Centering e Edges entrambi 1.0/10). Indagine e fix fatti nella stessa
sessione, ordinati per come sono stati scoperti — utile leggerli in ordine per capire cosa è
stato scartato e perché, prima di riprovare le stesse strade.

1. **Causa radice reale: il ritaglio esterno prendeva il contorno sbagliato.** Su una foto di test
   (carta su tavolo di legno chiaro), `_largest_contour` (Canny + contorno più grande) non trovava
   affatto il bordo fisico della carta — il bordo carta/legno produce un edge troppo debole/
   frammentato per Canny su quel tipo di sfondo. Il contorno più grande trovato era invece il
   frame blu dell'artwork **interno** alla carta (area ~6% dell'immagine, non l'85%+ atteso per
   il bordo fisico), e il fallback `cv2.minAreaRect` su quel contorno sbagliato produceva un
   rettangolo che sbandava nel tavolo su un lato — da cui il crop finale include legno vero e
   proprio, letto poi come "usura" nel calcolo edge wear (94.9% di usura misurata — implausibile
   per una carta in condizioni buone). **Diagnosticato salvando e ispezionando visivamente
   l'immagine normalizzata e i contorni intermedi**, non solo guardando i numeri finali — i numeri
   da soli non avrebbero rivelato che il problema era a monte, nel crop, non nelle formule.
2. **Primo tentativo di fix (scartato)**: segmentazione per distanza di colore dal colore di
   sfondo campionato agli angoli dell'immagine. Fallito: la venatura del legno ha variazioni di
   luminosità che superano comunque la soglia di distanza colore, quindi il contorno "foreground"
   seguiva le venature del legno invece del bordo della carta (verificato disegnando il contorno
   sull'immagine originale).
3. **Fix adottato**: segmentazione per **saturazione HSV** invece che per distanza di colore o
   gradiente. Verificato empiricamente su due foto: sfondo (tavolo) mediana saturazione ~21-31,
   carta mediana ~120-125 — separazione molto netta, stabile anche con texture marcata sullo
   sfondo. `_foreground_contour()` in `geometric_agent.py`, soglia `config.
   CARD_SATURATION_THRESHOLD`. Verificato visivamente (contorno disegnato sull'immagine
   originale) che segue perfettamente il bordo fisico reale su entrambe le foto di test
   (`test-image.jpg`, `test-image2.jpg`, nella root del repo).
4. **Aggiunta validazione di forma** (`_quad_is_plausible`) sul quadrilatero a 4 punti prima di
   fidarsi del perspective warp: proporzioni vicine a 63:88mm, angoli vicini a 90°. Prima di
   questo fix, un quadrilatero "trovato" ma storto veniva comunque usato ciecamente per il warp.
5. **Con il crop finalmente corretto, l'edge wear restava comunque alto (50-70%, non 0-10%
   plausibile).** Scomponendo la misura lato per lato è emerso che la deviazione è distribuita
   su tutti e 4 i lati (non concentrata su un lato solo, che avrebbe indicato un difetto reale) —
   sintomo di una **causa sistematica di calibrazione**, non di un bug di segmentazione: l'anello
   di riferimento (`EDGE_WEAR_REFERENCE_OFFSET_PX = 24px`, ~2mm) probabilmente cade già oltre il
   sottile bordo nero reale della carta, dentro il frame colorato — quindi si confronta "vero
   bordo nero" con "già non più bordo nero" su ogni carta, sistematicamente. **Non risolto**: la
   soglia per-lato (punto 3 di questa lista, comunque un miglioramento reale e verificato — vedi
   sopra "Pipeline") elimina i falsi positivi da gradiente di luce, ma la calibrazione mm→pixel
   dell'offset resta da tarare con foto reali di carte a condizione nota (vedi "Prossimo passo"
   sotto).
6. **Centering: nessun bug di segmentazione, ma un'assunzione strutturale sbagliata.** Verificato
   che sull'immagine ben ritagliata, il contorno più grande trovato da Canny copre solo ~22%
   dell'area carta — molto lontano dal range 55-95% assunto in `config.
   CENTERING_FRAME_AREA_RATIO_RANGE`. Motivo: una carta Yu-Gi-Oh ha titolo/artwork/testo come
   riquadri **separati**, non un unico frame continuo che Canny possa richiudere in un solo
   contorno — quindi "trova il contorno più grande in quel range" non trova quasi mai nulla, a
   prescindere dalla foto. Le validazioni aggiunte al punto successivo rendono il fallimento
   *onesto* (`detected: False` → fallback prudente 7.0/10) invece che silenzioso, ma non risolvono
   il rilevamento.
7. **Tentativo di redesign del centering (scartato)**: invece di cercare un contorno del frame,
   misurare lo spessore del bordo nero per lato scansionando il profilo di luminosità/saturazione
   dal margine verso l'interno (stessa idea del punto 3, applicata al bordo interno). Testato su
   entrambe le foto: il profilo non ha un salto netto (sfuma gradualmente per compressione JPEG/
   blur/riflessi), qualsiasi soglia scelta cade su un punto ambiguo della transizione. Risultato:
   scentrature implausibili (88-90% orizzontale) che non corrispondono a quanto si vede a occhio
   nelle foto. **Scartato prima di essere integrato nel codice** — non ha mai sostituito la
   versione precedente, `calculate_centering` resta quella del punto 6.
8. **Decisione presa: niente classificatore ML**. L'utente ha chiesto se un classificatore CV/ML
   allenato su un dataset di carte già gradate potesse sostituire questo approccio deterministico.
   Deciso di **non procedere**: (a) non esiste un dataset pubblico affidabile foto+grade per
   Yu-Gi-Oh — PSA/BGS non pubblicano immagini, uno scraping eBay darebbe foto con
   angolazioni/luci troppo incoerenti da normalizzare; (b) centering ed edge wear sono quantità
   geometriche misurabili direttamente — un classificatore ne perderebbe la trasparenza
   ("perché questo grade") che è un requisito esplicito del progetto, per rifare in modo opaco
   qualcosa che la CV può già misurare una volta tarata bene. La superficie (graffi/pieghe) resta
   l'unico sotto-voto dove un modello serve davvero, ed è già lì (VLM via Ollama).

9. **Edge wear ridisegnato: da distanza-da-riferimento a soglia assoluta di sbiancamento**
   (proposta dell'utente). Invece di confrontare il bordo con un anello di riferimento più
   interno (il problema di calibrazione del punto 5), si misura direttamente la % di pixel del
   bordo con luminosità sopra una soglia assoluta (`config.CARD_GRAYSCALE_WHITENESS_THRESHOLD`,
   180/255) — il bordo nero di una carta YGO è scuro a prescindere da illuminazione/carta, lo
   sbiancamento reale è inequivocabilmente chiaro, quindi non serve più nessun anello di
   riferimento. **Risolve anche il problema del punto 5** (niente più bisogno di sapere dove
   "finisce" il bordo nero in mm/pixel). Aggiunto `config.EDGE_WEAR_SKIN_PX` (2px) per escludere
   il residuo di blend/antialiasing del perspective warp esattamente sul confine del ritaglio,
   individuato per tentativi durante l'indagine del punto 5. **Verificato**: su
   `test-image.jpg`/`test-image2.jpg` (carte visivamente in condizioni buone) il risultato è
   0.07%/0.09% — plausibile, contro il 50-70% implausibile di prima del redesign.
10. **Corners implementato riusando la stessa soglia assoluta** (proposta dell'utente, con una
   precisazione tecnica emersa in fase di design — vedi il punto 3 della sezione Pipeline sopra
   sulla differenza sbiancamento/arrotondamento). Nuovo sotto-voto `corners_subgrade`, nuovo campo
   `GradingResult.corner_whitening_pct`, pesi ribilanciati (vedi "Grade finale" sopra). Chiude il
   limite "nessun sotto-voto Corners" che era documentato come scope limitation dalla prima
   versione del modulo. **Verificato**: stessi due file di test, risultato 0.99%/0.54%,
   coerente con angoli visivamente non consumati. Test end-to-end completo (con VLM reale via
   Ollama) su `test-image2.jpg`: grade finale 8.0/10 → EX, bottleneck su Centering (fallback
   prudenziale, non un difetto reale) — un risultato sensato, contro il 2.0/10 implausibile da cui
   è partita l'indagine di questa sezione.

11. **Bug trovato dall'utente guardando lo screenshot reale della UI: il crop "tagliava" il bordo
   nero della carta**, quindi anche gli angoli — non solo i numeri, ma l'immagine "Normalizzata +
   Analisi" mostrava visibilmente il frame colorato a contatto col margine, niente bordo nero
   visibile. Causa: il bordo nero di una carta YGO ha una saturazione HSV bassa (~20-40),
   praticamente indistinguibile da quella di un tavolo di legno (~20-30) — la segmentazione per
   saturazione (punto 3) quindi classifica il bordo nero **come sfondo**, e il quadrilatero
   rilevato si ferma al confine interno del bordo (dove inizia il frame colorato), non al vero
   bordo fisico. Misurato direttamente sui pixel: su `test-image2.jpg`, ~10-15px persi su una
   carta larga ~600px (~2-3% per lato) — esattamente la fascia che edge wear e corners dovrebbero
   analizzare, il che spiega perché quei sotto-voti risultavano quasi sempre vicini al massimo:
   non stavano guardando il bordo per niente.
   **Fix**: `_expand_quad()` in `geometric_agent.py` spinge i 4 punti del quadrilatero rilevato
   verso l'esterno, dal centroide, di `config.CARD_BORDER_EXPANSION_FRACTION` (3.5%, stimato dalla
   misura sopra con un margine di sicurezza) prima del perspective warp — applicato a entrambi i
   percorsi di rilevamento (quadrilatero validato o fallback `minAreaRect`), non solo al primo.
   **Verificato visivamente**: su entrambe le foto di test il bordo nero è ora visibile nel
   ritaglio; su `test-image.jpg` il risultato è netto, su `test-image2.jpg` resta un residuo — una
   sottile striscia di legno su un lato, perché quel lato era già leggermente asimmetrico prima
   dell'espansione (un'espansione uniforme non corregge un rilevamento già impreciso, sposta solo
   il problema). Percentuali risultanti dopo il fix: edge wear 0.02%/1.48%, corner whitening
   0.21%/6.57% (prima: praticamente 0 su entrambe) — non più sistematicamente a zero, più
   credibili, ma ancora **non validate contro una carta con usura reale nota** (vedi "Prossimo
   passo" sotto).

12. **Decisione finale: il ritaglio non è più automatico — lo fa l'utente.** Dopo il fix del
   punto 11, l'utente ha comunque trovato il crop poco convincente su uno screenshot reale della
   UI (il bordo nero appariva ancora tagliato in un punto). Invece di tentare un'altra euristica
   di rilevamento (saturazione, Canny, espansione: già 4 round in questa sessione, ognuno con un
   nuovo modo di sbagliare), l'utente ha deciso di eliminare il problema alla radice: **l'utente
   ritaglia la carta a mano**, trascinando 4 maniglie sugli angoli reali della foto caricata
   (`web/static/corner-picker.js`, vanilla JS senza dipendenze esterne — nessun conflitto con la
   scelta di progetto di non usare framework/build step JS). Rimossi da `geometric_agent.py`:
   `_quad_is_plausible`, `_largest_contour`, `_foreground_contour`, `_expand_quad` e le relative
   costanti in `config.py` (`CARD_SATURATION_THRESHOLD`, `CARD_BORDER_EXPANSION_FRACTION`) — non
   servono più, tutta la logica di rilevamento automatico è sparita. `CardDetectionError` è stata
   rinominata `CardCropError` (il significato è cambiato: non "non ho trovato il contorno" ma
   "i punti forniti non sono validi"). **Verificato**: con angoli scelti a mano vicino al vero
   bordo fisico su `test-image2.jpg`, il bordo nero è visibile su tutti i lati nel ritaglio
   (nessuno sconfinamento nel tavolo), e i sotto-voti risultano più credibili e meno
   sistematicamente "quasi perfetti" (corners sceso a 7.0/10, 14.2% di sbiancamento — plausibile
   per un'usura leggera reale, non uno zero automatico). Effetto collaterale positivo: la
   centering detection (punto 6, mai risolta) a volte scatta correttamente ora, probabilmente
   perché un crop più preciso rende il contorno del frame interno più regolare — non garantito,
   resta un limite noto.

### Prossimo passo (non ancora fatto)

Il ritaglio non è più il sospetto principale (ora è manuale, quindi preciso quanto lo è
l'utente) — resta però da validare la **calibrazione delle soglie di sbiancamento**
(`CARD_GRAYSCALE_WHITENESS_THRESHOLD = 180`, tabelle `EDGE_WEAR_PCT_TO_SUBGRADE`/
`CORNER_WHITENESS_PCT_TO_SUBGRADE`) contro una carta con usura reale nota, e il redesign del
centering (mai completato, vedi punto 7) resta un problema a parte, indipendente dalla qualità
del crop. Entrambi aspettano ancora **foto reali di carte con condizione nota** — da fare insieme
quando disponibili.

## Limiti noti (scope dichiarato in fase di design)

- **Corners misura solo lo sbiancamento, non l'arrotondamento geometrico**: vedi punto 3 della
  sezione Pipeline sopra — il perspective warp elimina l'informazione di forma dell'angolo per
  costruzione, quindi un angolo arrotondato ma non scolorito non verrebbe rilevato. Estensione
  futura possibile: analizzare la curvatura vicino ai 4 punti scelti dall'utente **prima** del
  warp, in `normalize_card_image`.
- **Centering non sempre rilevato**: vedi punto 6 della cronologia sopra — limite noto, non
  risolto in questa sessione (anche se un crop manuale preciso lo rende meno frequente).
- **Il ritaglio manuale richiede attenzione dell'utente**: se i 4 angoli sono piazzati in modo
  impreciso, l'errore si propaga a valle (edge wear, corners, centering) esattamente come
  succedeva col rilevamento automatico — la differenza è che ora l'utente vede il quadrilatero
  che sta per confermare (overlay live in `corner-picker.js`) invece di fidarsi ciecamente di
  un'euristica.
- **Formula non validata empiricamente**: soglie e pesi sono ipotesi di design ragionevoli, non
  calibrate su un dataset di carte gradate professionalmente (vedi "Prossimo passo" sopra).
- **Dipendenza da Ollama locale**: se il server non è raggiungibile, l'intera pipeline fallisce
  con `InspectorAgentError` (nessun grade parziale calcolato senza il giudizio di superficie).
