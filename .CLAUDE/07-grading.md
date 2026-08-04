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
   contorno nell'immagine.
2. `geometric_agent.calculate_edge_wear(img)` — confronta un anello perimetrale sottile
   (`config.EDGE_WEAR_BORDER_PX`, default 8px) con un anello di riferimento più interno
   (`config.EDGE_WEAR_REFERENCE_OFFSET_PX`, default 24px), calcolando la % di pixel che si
   discostano per colore oltre `config.EDGE_WEAR_COLOR_DISTANCE_THRESHOLD` (default 40.0, distanza
   euclidea in BGR).
3. `geometric_agent.calculate_centering(img)` — cerca un contorno quadrilatero la cui area rientra
   in `config.CENTERING_FRAME_AREA_RATIO_RANGE` (default 0.55-0.95 dell'area totale della carta) e
   ne misura i margini rispetto ai bordi fisici, ritornando i rapporti orizzontale/verticale
   (50/50 = perfetto) e un flag `detected`.
4. `ai_agent.InspectorAgent.analyze_surface(img)` — invia l'immagine **già normalizzata** al
   modello `llava` via Ollama locale (`config.OLLAMA_BASE_URL`), con
   `config.INSPECTOR_SYSTEM_PROMPT` (fisso, fornito dall'utente in fase di design — non
   modificarne lo schema JSON senza aggiornare anche il parsing in `ai_agent.py`), `format="json"`,
   `temperature=0.1`. Ritorna `has_scratches`, `scratch_severity`, `has_creases`,
   `crease_severity`, `details`.

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
