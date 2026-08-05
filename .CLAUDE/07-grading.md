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

1. `geometric_agent.normalize_card_image(path)` — rileva il contorno della carta e fa perspective
   warp verso un rettangolo canonico (`config.NORMALIZED_CARD_WIDTH/HEIGHT`, default 750x1047,
   proporzione fisica di una carta TCG 63x88mm). Solleva `CardDetectionError` se non trova alcun
   contorno nell'immagine. Il rilevamento del contorno esterno è a due strategie (vedi
   "Cronologia: indagine precisione CV" più sotto per il perché):
   - `_foreground_contour(image)` — segmentazione per **saturazione HSV** (`config.
     CARD_SATURATION_THRESHOLD`, default 60): una carta stampata è sempre molto più satura di
     un tavolo/sfondo, anche se quello ha una texture marcata (es. venatura del legno). Strategia
     primaria, molto più robusta della successiva su sfondi "rumorosi".
   - `_largest_contour(gray)` — il vecchio approccio Canny + contorno più grande. Usato solo
     come fallback se la segmentazione per saturazione non produce un contorno con area
     plausibile (10%-95% dell'immagine totale).
   - Il contorno scelto (quale dei due) viene poi semplificato a 4 punti (`approxPolyDP`) e
     validato da `_quad_is_plausible()` (proporzioni vicine a 63:88 entro il 15%, angoli vicini
     a 90° entro 25°) prima di fidarsi del perspective warp a 4 punti; se il quadrilatero non è
     plausibile (angoli storti, proporzioni sbagliate — tipico di un edge rumoroso), si usa
     invece `cv2.minAreaRect(contour)` come crop+rotate più semplice e meno sensibile al rumore
     sui singoli punti.
2. `geometric_agent.calculate_edge_wear(img)` — confronta un anello perimetrale sottile
   (`config.EDGE_WEAR_BORDER_PX`, default 8px) con un anello di riferimento più interno
   (`config.EDGE_WEAR_REFERENCE_OFFSET_PX`, default 24px), calcolando la % di pixel che si
   discostano per colore oltre `config.EDGE_WEAR_COLOR_DISTANCE_THRESHOLD` (default 40.0, distanza
   euclidea in BGR). **Il colore di riferimento è calcolato per singolo lato** (top/bottom/left/
   right indipendenti, non un unico mediano per tutta la carta) — un gradiente di luce
   direzionale altrimenti veniva letto come usura sui lati più scuri/chiari. Ritorna una tupla
   `(pct, damaged_mask)`: `damaged_mask` è una maschera booleana (h,w) con esattamente i pixel
   segnalati come usurati, usata per l'overlay visivo (vedi sezione "Trasparenza" sotto).
3. `geometric_agent.calculate_centering(img)` — cerca un contorno quadrilatero la cui area rientra
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
4. `ai_agent.InspectorAgent.analyze_surface(img)` — invia l'immagine **già normalizzata** al
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
- **Surface**: `config.SEVERITY_TO_SUBGRADE` mappa `"none"→10, "light"→7, "heavy"→3`; si prende il
  **minimo** tra il subgrade di `scratch_severity` e quello di `crease_severity` (un solo difetto
  serio abbassa comunque il voto di superficie). Stringa di severità inattesa dal VLM →
  `config.UNKNOWN_SEVERITY_FALLBACK_SUBGRADE` (7.0), per non premiare né penalizzare
  eccessivamente un output malformato.

## Grade finale

```
weighted_avg = centering_subgrade * 0.20 + edges_subgrade * 0.30 + surface_subgrade * 0.50
final_grade  = min(weighted_avg, min(centering_subgrade, edges_subgrade, surface_subgrade) + 1.0)
final_grade  = round(final_grade * 2) / 2   # arrotondato a step di 0.5
```

Pesi in `config.GRADE_SUBGRADE_WEIGHTS`. Il cap "peggior sotto-voto + 1.0" è una regola in stile
BGS: un singolo difetto grave non può essere "nascosto" da una media pesata favorevole. I pesi
riflettono che i difetti di superficie pesano di più sul valore percepito/di rivendita rispetto a
un lieve decentramento — sono un punto di partenza ragionevole, **non validato su un dataset reale
di carte**: da tarare osservando i risultati.

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
capire perché si ottiene un certo grade (non solo i numeri nudi).

- `CardGrader.grade_card()` ritorna **una tupla** `(GradingResult, DebugImages)`, non solo
  `GradingResult` — attenzione se si aggiungono nuovi call site. `DebugImages` (dataclass in
  `grader.py`, non Pydantic — contiene `PIL.Image.Image`, non serializzabili e non persistite in
  `collection.json`) ha due campi:
  - `original` — la foto così com'è stata caricata, nessuna elaborazione.
  - `annotated` — l'immagine normalizzata (`normalize_card_image`) con overlay disegnati da
    `geometric_agent.build_annotated_image(normalized_img, damaged_mask, centering)`: rettangolo
    giallo sulla banda perimetrale controllata per l'usura, pixel rossi esattamente dove
    `damaged_mask` è `True`, rettangolo ciano sul frame di centratura rilevato (`centering["bbox"]`,
    solo se `detected=True`). Una singola immagine risponde quindi sia a "come viene
    ritagliata/centrata" sia a "quali analisi vengono fatte".
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

### Prossimo passo (non ancora fatto)

Sia la calibrazione edge-wear (punto 5) sia un vero redesign del centering (punto 6/7) sono
bloccati sulla stessa cosa: **foto reali di carte con condizione nota**, per capire dove cade
davvero la soglia invece di tararla a intuito. Da fare insieme quando disponibili, prima di
riprovare altre euristiche alla cieca — i tentativi ai punti 2 e 7 sono stati scartati proprio
perché prodotti senza un riferimento di verità con cui confrontarsi.

## Limiti noti (scope dichiarato in fase di design)

- **Nessun sotto-voto "Corners"**: il PSA/BGS reale ne ha 4 (Centering, Corners, Edges, Surface);
  qui solo 3, perché né l'agente geometrico né il prompt del VLM (che ignora esplicitamente bordi
  e centratura) coprono il rilevamento di angoli consumati/arrotondati. Estensione futura
  possibile: aggiungere un rilevamento del raggio di curvatura/whitening sui 4 angoli in
  `geometric_agent.py`.
- **Formula non validata empiricamente**: soglie e pesi sono ipotesi di design ragionevoli, non
  calibrate su un dataset di carte gradate professionalmente.
- **Dipendenza da Ollama locale**: se il server non è raggiungibile, l'intera pipeline fallisce
  con `InspectorAgentError` (nessun grade parziale calcolato senza il giudizio di superficie).
