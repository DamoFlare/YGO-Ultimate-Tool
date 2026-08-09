# Grading Module (deterministic CV + local VLM)

Hybrid architecture with 2 agents + an orchestrator, in `services/grading/`. Entirely replaces
the old placeholder OCR scanner. Goal: given a path to a photo of a physical card,
compute a 1-10 PSA/BGS-style grade and map it onto the NM/EX/GD/LP/PO condition scale already
used for pricing (`config.CONDITION_MULTIPLIERS`).

## Why hybrid (CV + VLM) and not just pixel-diffing

A 1:1 comparison against a reference "Mint" card was ruled out at design time because
ambient noise, lighting, and print centering generate too many false positives. Instead, the
problem is split:
- **Measurable geometric defects** (edge wear, centering) → deterministic CV, no AI,
  reproducible results.
- **Surface defects that require visual judgment** (scratches, creases) → local VLM, because
  they aren't easily expressible as mathematical pixel thresholds.

## Pipeline (`services/grading/grader.py`, class `CardGrader.grade_card()`)

1. `geometric_agent.normalize_card_image(path, corners)` — performs a perspective warp of the
   quadrilateral **provided by the caller** (the card's 4 corners, in pixel coordinates of the
   original photo) onto a canonical rectangle (`config.NORMALIZED_CARD_WIDTH/HEIGHT`, default
   750x1047, the physical aspect ratio of a 63x88mm TCG card). Raises `CardCropError` if the
   image can't be opened or if `corners` doesn't contain exactly 4 points.
   **The outline is no longer detected automatically** — the user crops it by hand on the web
   page (`web/static/corner-picker.js`: drags 4 handles over the uploaded photo,
   `POST /grading/analyze` receives `corners` as a JSON string alongside the image file). Several
   rounds of automatic detection (Canny, HSV saturation segmentation, shape validation,
   border expansion) were attempted and abandoned within the same session — see
   "History: CV accuracy investigation" further below for the full story of what didn't
   work and why manual cropping was adopted instead.
2. `geometric_agent.calculate_edge_wear(img)` — extracts the thin perimeter band
   (`config.EDGE_WEAR_BORDER_PX`, default 5px, excluding the first `config.EDGE_WEAR_SKIN_PX`
   pixels closest to the crop's edge) and computes the % of pixels with brightness (grayscale)
   above `config.CARD_GRAYSCALE_WHITENESS_THRESHOLD` (default 180/255) — an **absolute threshold
   on whitening**, no longer a relative distance from a reference ring (see "History"
   below for why the latter was abandoned). Returns a tuple `(pct, damaged_mask)`:
   `damaged_mask` is a boolean (h,w) mask with exactly the pixels flagged as whitened,
   used for the visual overlay (see the "Transparency" section below).
3. `geometric_agent.calculate_corner_whitening(img)` — the same absolute-threshold logic as
   `calculate_edge_wear`, applied to a square ROI (`config.CORNER_ROI_PX`, default 50px) for
   each of the 4 corners, inset by the same `EDGE_WEAR_SKIN_PX`. It only measures **whitening**
   (a color defect that survives the perspective warp), not the corner's **geometric rounding** —
   that's a shape defect the warp eliminates by construction (it forces any detected point near
   the corner to coincide exactly with the ideal vertex of the destination rectangle). Detecting
   rounding, if ever implemented, would need to happen on the outline points **before** the warp;
   it is not implemented.
4. `geometric_agent.calculate_centering(img)` — looks for a quadrilateral outline whose area
   falls within `config.CENTERING_FRAME_AREA_RATIO_RANGE` (default 0.55-0.95 of the card's total
   area), **doesn't touch the image edges** (otherwise it's almost certainly the card's outer
   edge being detected again, not the inner frame) and is a **convex quadrilateral**
   (`approxPolyDP` to 4 points + `cv2.isContourConvex`), and measures its margins relative to the
   physical edges, returning horizontal/vertical ratios (50/50 = perfect), a `detected` flag, and
   `bbox` (x,y,w,h of the detected frame, `None` if not detected) — this too is used only for the
   visual overlay, not for computing the subgrade. **In practice (see history below), `detected`
   is almost always `False`**: the print frame's outline rarely satisfies these constraints, so
   the centering subgrade almost always falls back to the cautious fallback — a known limitation,
   not yet resolved.
5. `ai_agent.InspectorAgent.analyze_surface(img)` — sends the **already normalized** image to
   the `llava` model via local Ollama (`config.OLLAMA_BASE_URL`), with
   `config.INSPECTOR_SYSTEM_PROMPT` (fixed in terms of the JSON schema — don't change it without
   also updating the parsing in `ai_agent.py`; the text content requested for `details` is,
   however, freely editable), `format="json"`, `temperature=0.1`. Returns `has_scratches`,
   `scratch_severity`, `has_creases`, `crease_severity`, `details` (2-3 sentences describing what
   was observed, where on the card, and the confidence level — extended from "1 sentence" to give
   more context in the UI).

## Computing the subgrades (1-10)

- **Centering**: if `centering["detected"]` is `True`, the worst deviation is computed as
  `max(|horizontal-50|, |vertical-50|)` and looked up in `config.CENTERING_DEVIATION_TO_SUBGRADE`
  (an ordered list of ascending thresholds `(max_deviation, subgrade)`, e.g. ≤2%→10, ≤5%→9, ...);
  beyond the last threshold, `config.CENTERING_MIN_SUBGRADE` is used. If `detected` is `False`
  (frame not detected with confidence), `config.CENTERING_FALLBACK_SUBGRADE` (default 7.0) is
  used directly instead of assuming perfect centering.
- **Edges**: same ascending-threshold scheme on `edge_wear_pct`, table
  `config.EDGE_WEAR_PCT_TO_SUBGRADE`, fallback `config.EDGE_WEAR_MIN_SUBGRADE`.
- **Corners**: same ascending-threshold scheme on `corner_whitening_pct`, table
  `config.CORNER_WHITENESS_PCT_TO_SUBGRADE` (same shape as the Edges table — same physical
  measurement, different region), fallback `config.CORNER_MIN_SUBGRADE`.
- **Surface**: `config.SEVERITY_TO_SUBGRADE` maps `"none"→10, "light"→7, "heavy"→3`; the
  **minimum** of the `scratch_severity` subgrade and the `crease_severity` subgrade is taken (a
  single serious defect still lowers the surface score). An unexpected severity string from the
  VLM → `config.UNKNOWN_SEVERITY_FALLBACK_SUBGRADE` (7.0), so as not to excessively reward or
  penalize a malformed output.

## Final grade

```
weighted_avg = centering_subgrade * 0.16 + edges_subgrade * 0.24 + corners_subgrade * 0.20 + surface_subgrade * 0.40
final_grade  = min(weighted_avg, min(centering_subgrade, edges_subgrade, corners_subgrade, surface_subgrade) + 1.0)
final_grade  = round(final_grade * 2) / 2   # rounded to steps of 0.5
```

Weights in `config.GRADE_SUBGRADE_WEIGHTS`. The "worst subgrade + 1.0" cap is a BGS-style
rule: a single severe defect can't be "hidden" by a favorable weighted average. The
centering/edges/surface weights were originally 20/30/50; when corners was added they were
scaled proportionally (×0.8) to make room for corners=0.20, preserving the relative ratio between
the three instead of picking a new one by feel. A reasonable starting point,
**not validated against a real dataset of cards**: to be tuned by observing results.

## Grade → market condition mapping

`config.GRADE_TO_CONDITION` (list ordered by descending threshold):

| Final grade | Condition |
|---|---|
| ≥ 8.5 | NM |
| ≥ 7.0 | EX |
| ≥ 5.5 | GD |
| ≥ 4.0 | LP |
| < 4.0 | PO (`config.GRADE_TO_CONDITION_FALLBACK`) |

The result (`GradingResult.condition`) feeds into `CollectionItem.condition`, used by
`CollectionItem.effective_price`/`total_effective_price` to show the "real" value of the
graded copy alongside the theoretical NM estimate in `CollectionView`.

## How to tune the formula

All thresholds/weights are named constants in `config.py` (section "Grading Module" /
"Geometric Agent thresholds") — modifiable without touching the logic in `grader.py` or
`geometric_agent.py`. If the perceived grade is systematically too high/low compared to
known physical cards, the first place to act is the weights in
`config.GRADE_SUBGRADE_WEIGHTS` or the `*_TO_SUBGRADE` thresholds.

## Transparency: debug images and grade explanation

Added after the user asked to be able to see the uploaded photo, how it's cropped, and
understand why a given grade is produced (not just the bare numbers). Since cropping became
manual (see item 12 of the history below), "how it's cropped" is shown **before**
the analysis, not only after: `web/static/corner-picker.js` draws a live polygon over the
preview of the uploaded photo while the user drags the 4 corners, so the user sees
exactly which quadrilateral is about to be passed to the perspective warp, not just the final
result. While dragging, a **magnifying glass** also appears (`#cropper-magnifier`,
3x zoom, CSS `background-position`/`background-size` technique — no canvas) centered above the
touched point (it moves below if too close to the top margin, so it doesn't get cut
off the preview), with crosshairs at its center, so the corner can be placed with sub-pixel
precision without the cursor/finger covering the exact point.

## Bulk Grading and the "pending" inbox (`AppState.pending_gradings`)

The user asked to be able to grade multiple photos in sequence (selecting multiple files or
an entire folder), cropping each by hand as in the single-photo flow, **and** to be able to
retrieve the graded cards later to link them to the collection — not necessarily right after
the analysis.

This required an architectural change, not just "adding a loop": previously there was
`AppState.last_grading_result`/`last_debug_images`, a single slot that assumed "there is always
at most one analysis awaiting linking". With multiple photos analyzed one after another, what's
needed instead is a **list**: `AppState.pending_gradings` (`List[PendingGrading]`, each with
`id`/`filename`/`result`/`debug_images`), populated by both the single-photo flow and the bulk
one — a single "inbox" for both, not two parallel mechanisms. `add_pending_grading`/
`get_pending_grading`/`remove_pending_grading` in `web/state.py` are the only places that touch
it.

**Persisted to file** (`config.DEFAULT_PENDING_GRADINGS_FILE`, `pending_gradings.json`,
gitignored — unlike `collection.json` it contains photos), not just in memory: the user graded
several cards in bulk and wants to be able to link them at leisure later, even after a server
restart, without having to repeat photo+crop+analysis. `PendingGrading.to_dict()`/`from_dict()`
also serialize the two images (`DebugImages`, otherwise not JSON-serializable) as base64
**JPEG**, not PNG: they're photographs, not graphics with sharp outlines, and lossless PNG
brought a single pending card to ~4.3MB — with a dozen queued from a bulk session before linking
them, the file grew quickly. JPEG quality 85 brings the same case down to ~740KB (measured),
pixel-perfect fidelity isn't needed for a "which card is this" purpose.
`AppState._load_pending_gradings()`/`_save_pending_gradings()` perform synchronous I/O on every
add/remove (same try/except-with-print pattern as `services/storage.py`, not typed exceptions —
consistent with that convention, different from the rest of the Grading module, because this is
generic persistence in `web/state.py`, not grading logic).

Consequence on the "Link to a card" flow: it's no longer a single, implicit search box
("link the most recently analyzed one"), but a per-row action in the pending list
(`_grading_pending.html`, "🔗 Link" → search box scoped to that `id` →
`POST /grading/save` with an explicit `pending_id`) — necessary because with several cards
queued at once there's no longer a single "last one" to implicitly act on. Full routing/template
details in [05-ui.md](05-ui.md); the architectural point here: Bulk Grading doesn't duplicate the
analysis/save logic, it reuses exactly the single-photo flow's `POST /grading/analyze` (one call
per photo, via `fetch()` from the client-side sequencer in `corner-picker.js`) and
`POST /grading/save` (one call per link).

- `CardGrader.grade_card()` returns **a tuple** `(GradingResult, DebugImages)`, not just
  `GradingResult` — watch out if adding new call sites. `DebugImages` (a dataclass in
  `grader.py`, not Pydantic — it contains `PIL.Image.Image`, which isn't serializable and isn't
  persisted in `collection.json`) has two fields:
  - `original` — the photo exactly as uploaded, no processing.
  - `annotated` — the normalized image (`normalize_card_image`) with overlays drawn by
    `geometric_agent.build_annotated_image(normalized_img, damaged_mask, centering,
    corner_damaged_mask)`: a yellow rectangle on the perimeter band checked for wear,
    orange rectangles on the 4 corner ROIs checked for whitening, red pixels exactly where
    `damaged_mask`/`corner_damaged_mask` are `True`, a cyan rectangle on the detected centering
    frame (`centering["bbox"]`, only if `detected=True`). A single image thus answers both
    "how is it cropped/centered" and "what analyses are performed".
- Shown on the web page (`web/routers/grading.py` + `templates/_grading_result.html`) as
  `<img src="data:image/png;base64,...">` — `web.state.image_to_data_uri(pil_image)` encodes
  each `PIL.Image` as PNG and embeds it directly in the response HTML. No temporary file to
  serve, no graphics protocol, scaling handled natively by the browser via
  CSS (`max-width: 100%` on `.grading-images img`).
- `GradingResult.explanation` (string field) — a deterministic explanation generated by
  `grader._build_explanation()`: identifies which subgrade is the "bottleneck" (the
  minimum of the three, the one that determines the `worst + 1.0` cap) and composes 2-3
  sentences in English that connect number→cause→effect on the final grade. Distinct from the
  VLM's free text (`surface_details["details"]`), shown separately as "What the AI saw".

Historical note: the first version of this section showed the images in a Textual TUI
via the `textual-image` library. It caused two non-trivial library bugs (layout
overlap, then images not scaled correctly to the box) — this was the direct reason the
entire app was rebuilt as a web app. See
[06-notes-and-discrepancies.md](06-notes-and-discrepancies.md) for the full history. The problem
is completely absent in the current web implementation: an `<img>` with `max-width: 100%` doesn't
have these edge cases.

## History: CV accuracy investigation (crop, edge wear, centering)

The user reported that the computed grades seemed inaccurate (e.g. a card in good condition
graded 2.0/10 with Centering and Edges both at 1.0/10). Investigation and fixes done in the same
session, ordered by how they were discovered — useful to read in order to understand what was
discarded and why, before retrying the same approaches.

1. **Real root cause: the outer crop was picking up the wrong outline.** On a test photo
   (card on a light wood table), `_largest_contour` (Canny + largest contour) didn't find
   the card's physical edge at all — the card/wood boundary produces too weak/
   fragmented an edge for Canny on that kind of background. The largest contour found was instead
   the blue artwork frame **inside** the card (area ~6% of the image, not the 85%+ expected for
   the physical edge), and the `cv2.minAreaRect` fallback on that wrong contour produced a
   rectangle that drifted onto the table on one side — hence the final crop includes actual
   wood, later read as "wear" in the edge wear calculation (94.9% wear measured — implausible
   for a card in good condition). **Diagnosed by saving and visually inspecting the
   normalized image and the intermediate contours**, not just by looking at the final numbers —
   the numbers alone wouldn't have revealed that the problem was upstream, in the crop, not in
   the formulas.
2. **First fix attempt (discarded)**: segmentation by color distance from the background
   color sampled at the image corners. Failed: wood grain has brightness variations that still
   exceed the color-distance threshold, so the "foreground" contour followed the wood grain
   instead of the card's border (verified by drawing the contour on the original image).
3. **Fix adopted**: segmentation by **HSV saturation** instead of color distance or
   gradient. Verified empirically on two photos: background (table) median saturation ~21-31,
   card median ~120-125 — a very clean separation, stable even with pronounced background
   texture. `_foreground_contour()` in `geometric_agent.py`, threshold `config.
   CARD_SATURATION_THRESHOLD`. Verified visually (contour drawn on the original image)
   that it perfectly follows the actual physical edge on both test photos
   (`test-image.jpg`, `test-image2.jpg`, in the repo root).
4. **Added shape validation** (`_quad_is_plausible`) on the 4-point quadrilateral before
   trusting the perspective warp: proportions close to 63:88mm, angles close to 90°. Before
   this fix, a "found" but skewed quadrilateral was still used blindly for the warp.
5. **With the crop finally correct, edge wear still remained high (50-70%, not the plausible
   0-10%).** Breaking the measurement down side by side revealed that the deviation is
   distributed across all 4 sides (not concentrated on a single side, which would have indicated
   a real defect) — a symptom of a **systematic calibration cause**, not a segmentation bug: the
   reference ring (`EDGE_WEAR_REFERENCE_OFFSET_PX = 24px`, ~2mm) probably already falls beyond
   the card's actual thin black border, inside the colored frame — so "true black border" is
   being compared against "already no longer black border" on every card, systematically.
   **Not resolved**: the per-side threshold (item 3 in this list, still a real and verified
   improvement — see "Pipeline" above) eliminates false positives from light gradients, but the
   mm→pixel calibration of the offset still needs to be tuned with real photos of cards in known
   condition (see "Next step" below).
6. **Centering: no segmentation bug, but a wrong structural assumption.** Verified that on
   the well-cropped image, the largest contour found by Canny covers only ~22% of the card
   area — far from the 55-95% range assumed in `config.CENTERING_FRAME_AREA_RATIO_RANGE`.
   Reason: a Yu-Gi-Oh card has title/artwork/text as **separate** boxes, not a single continuous
   frame that Canny can close into one contour — so "find the largest contour in that range"
   almost never finds anything, regardless of the photo. The validations added in the next item
   make the failure *honest* (`detected: False` → cautious fallback of 7.0/10) instead of silent,
   but they don't fix the detection itself.
7. **Attempted centering redesign (discarded)**: instead of looking for a frame contour,
   measure the black border's thickness per side by scanning the brightness/saturation
   profile from the margin inward (same idea as item 3, applied to the inner border). Tested on
   both photos: the profile has no sharp jump (it fades gradually due to JPEG compression/
   blur/reflections), so any chosen threshold lands on an ambiguous point of the transition.
   Result: implausible off-centering (88-90% horizontal) that doesn't match what's visible to
   the eye in the photos. **Discarded before being integrated into the code** — it never
   replaced the previous version; `calculate_centering` remains the one from item 6.
8. **Decision made: no ML classifier**. The user asked whether a CV/ML classifier trained on
   a dataset of already-graded cards could replace this deterministic approach. Decided **not to
   proceed**: (a) there's no reliable public photo+grade dataset for Yu-Gi-Oh — PSA/BGS don't
   publish images, and eBay scraping would yield photos with angles/lighting too inconsistent to
   normalize; (b) centering and edge wear are geometric quantities that can be measured directly
   — a classifier would lose the transparency ("why this grade") that is an explicit project
   requirement, in order to opaquely redo something CV can already measure once properly tuned.
   Surface (scratches/creases) remains the only subgrade where a model is genuinely needed, and
   it's already there (VLM via Ollama).

9. **Edge wear redesigned: from distance-from-reference to an absolute whitening threshold**
   (user's proposal). Instead of comparing the border against a more inward reference ring
   (the calibration problem from item 5), the % of border pixels with brightness above an
   absolute threshold is measured directly (`config.CARD_GRAYSCALE_WHITENESS_THRESHOLD`,
   180/255) — a YGO card's black border is dark regardless of lighting/card, and real
   whitening is unambiguously light, so no reference ring is needed anymore. **This also solves
   the problem from item 5** (no more need to know where the black border "ends" in mm/pixels).
   Added `config.EDGE_WEAR_SKIN_PX` (2px) to exclude the perspective warp's blend/antialiasing
   residue right at the edge of the crop, found by trial and error during the item 5
   investigation. **Verified**: on `test-image.jpg`/`test-image2.jpg` (cards visually in good
   condition) the result is 0.07%/0.09% — plausible, versus the implausible 50-70% before the
   redesign.
10. **Corners implemented reusing the same absolute threshold** (user's proposal, with a
   technical clarification that emerged during design — see item 3 of the Pipeline section
   above on the whitening/rounding difference). New subgrade `corners_subgrade`, new field
   `GradingResult.corner_whitening_pct`, rebalanced weights (see "Final grade" above). Closes
   the "no Corners subgrade" limitation that had been documented as a scope limitation since the
   module's first version. **Verified**: same two test files, result 0.99%/0.54%, consistent
   with visually unworn corners. Full end-to-end test (with a real VLM via Ollama) on
   `test-image2.jpg`: final grade 8.0/10 → EX, bottleneck on Centering (a cautious fallback, not
   a real defect) — a sensible result, versus the implausible 2.0/10 this section's investigation
   started from.

11. **Bug found by the user looking at a real UI screenshot: the crop was "cutting off" the
   card's black border**, and therefore the corners too — not just the numbers: the "Normalized +
   Analysis" image visibly showed the colored frame touching the margin, no black border visible.
   Cause: a YGO card's black border has low HSV saturation (~20-40), practically
   indistinguishable from that of a wood table (~20-30) — saturation segmentation (item 3)
   therefore classifies the black border **as background**, and the detected quadrilateral stops
   at the border's inner boundary (where the colored frame begins), not at the true physical
   edge. Measured directly on pixels: on `test-image2.jpg`, ~10-15px lost on a card ~600px wide
   (~2-3% per side) — exactly the band edge wear and corners are supposed to analyze, which
   explains why those subgrades almost always came out near the maximum: they weren't looking at
   the edge at all.
   **Fix**: `_expand_quad()` in `geometric_agent.py` pushes the detected quadrilateral's 4 points
   outward, from the centroid, by `config.CARD_BORDER_EXPANSION_FRACTION` (3.5%, estimated from
   the measurement above with a safety margin) before the perspective warp — applied to both
   detection paths (validated quadrilateral or `minAreaRect` fallback), not just the first.
   **Verified visually**: on both test photos the black border is now visible in the
   crop; on `test-image.jpg` the result is clean, on `test-image2.jpg` a residue remains — a
   thin strip of wood on one side, because that side was already slightly asymmetric before
   the expansion (a uniform expansion doesn't fix an already-imprecise detection, it just shifts
   the problem). Resulting percentages after the fix: edge wear 0.02%/1.48%, corner whitening
   0.21%/6.57% (before: practically 0 on both) — no longer systematically zero, more
   credible, but still **not validated against a card with known real wear** (see "Next
   step" below).

12. **Final decision: cropping is no longer automatic — the user does it.** After the fix
   from item 11, the user still found the crop unconvincing on a real UI screenshot (the black
   border still appeared cut off in one spot). Instead of trying yet another detection
   heuristic (saturation, Canny, expansion: already 4 rounds in this session, each with a new
   way to get it wrong), the user decided to eliminate the problem at the root: **the user crops
   the card by hand**, dragging 4 handles onto the real corners of the uploaded photo
   (`web/static/corner-picker.js`, vanilla JS with no external dependencies — no conflict with
   the project's choice not to use JS frameworks/build steps). Removed from
   `geometric_agent.py`: `_quad_is_plausible`, `_largest_contour`, `_foreground_contour`,
   `_expand_quad`, and the related constants in `config.py` (`CARD_SATURATION_THRESHOLD`,
   `CARD_BORDER_EXPANSION_FRACTION`) — no longer needed, all the automatic detection logic is
   gone. `CardDetectionError` was renamed to `CardCropError` (the meaning changed: no longer
   "I didn't find the outline" but "the provided points aren't valid"). **Verified**: with
   corners chosen by hand close to the true physical edge on `test-image2.jpg`, the black
   border is visible on all sides in the crop (no overrun into the table), and the subgrades
   come out more credible and less systematically "near-perfect" (corners dropped to 7.0/10,
   14.2% whitening — plausible for real light wear, not an automatic zero). Positive side
   effect: centering detection (item 6, never resolved) now sometimes triggers correctly,
   probably because a more precise crop makes the inner frame's outline more regular — not
   guaranteed, remains a known limitation.
13. **Added Bulk Grading + the shared "pending" inbox.** At the user's request: selecting
   multiple photos/a whole folder, the same manual 4-corner cropping applied one photo at a
   time, automatic analysis after each confirmation. This required replacing the single slot
   `last_grading_result`/`last_debug_images` with a list (`AppState.pending_gradings`) shared by
   both the single-photo flow and the bulk one, and moving "Link to a card" from an implicit
   search box ("the most recently analyzed one") to an explicit per-row action (`pending_id`) —
   necessary with multiple cards queued at once. See "Bulk Grading and the pending inbox" above
   and [05-ui.md](05-ui.md) for routing/template details. **Verified** with `TestClient`: two
   consecutive analyses populate the inbox with 2 independent rows, search+save scoped to a
   specific `pending_id` removes only that entry, discarding a nonexistent `pending_id` returns
   an error message instead of a 500.
14. **Bulk Grading: cropping and analysis split into two phases** (at the user's request,
   after trying v1). In the first version, every crop confirmation immediately launched the
   analysis of that same photo, forcing a wait (VLM analysis included, a few seconds) before
   being able to crop the next photo — the user had to stay in front of the screen for the
   whole queue. Redesigned into two client-side phases (`corner-picker.js`): **all** the photos
   in the queue are cropped one after another with no network calls at all, then — once cropping
   is complete — analysis runs in sequence on all the cropped photos, with no further user input
   (one `fetch()` request at a time to `/grading/analyze`, unchanged server-side). The user can
   step away during the analysis phase; the limitation is that the loop lives in the browser
   tab, so it stops if the tab is closed (it's not a server-side job) — see "Known limitations"
   below. **In the same request**, the pending inbox was made persistent to file (see the
   dedicated section above), for the same underlying need: grading many cards in one bulk
   session and being able to link them at leisure, even across a server restart.

### Next step (not done yet)

Cropping is no longer the primary suspect (it's now manual, so as precise as the user is) —
what remains to be validated, though, is the **calibration of the whitening thresholds**
(`CARD_GRAYSCALE_WHITENESS_THRESHOLD = 180`, tables `EDGE_WEAR_PCT_TO_SUBGRADE`/
`CORNER_WHITENESS_PCT_TO_SUBGRADE`) against a card with known real wear, and the centering
redesign (never completed, see item 7) remains a separate problem, independent of crop quality.
Both are still waiting on **real photos of cards with known condition** — to be done together
once available.

## Known limitations (scope declared at design time)

- **Corners only measures whitening, not geometric rounding**: see item 3 of the
  Pipeline section above — the perspective warp eliminates the corner's shape information by
  construction, so a rounded but not discolored corner wouldn't be detected. Possible future
  extension: analyze the curvature near the 4 points chosen by the user **before** the
  warp, in `normalize_card_image`.
- **Centering not always detected**: see item 6 of the history above — a known limitation,
  not resolved in this session (although a precise manual crop makes it less frequent).
- **Manual cropping requires the user's attention**: if the 4 corners are placed
  imprecisely, the error propagates downstream (edge wear, corners, centering) exactly as it did
  with automatic detection — the difference is that the user now sees the quadrilateral about
  to be confirmed (live overlay in `corner-picker.js`) instead of blindly trusting a heuristic.
- **Formula not empirically validated**: thresholds and weights are reasonable design
  hypotheses, not calibrated against a dataset of professionally graded cards (see "Next step"
  above).
- **Dependency on local Ollama**: if the server isn't reachable, the entire pipeline fails
  with `InspectorAgentError` (no partial grade is computed without the surface judgment).
- **"Pending" inbox persisted but not versioned**: `pending_gradings.json` survives a
  server restart (see the dedicated section above), but it's gitignored and written with a
  simple synchronous `json.dump` on every add/remove — no backup, no migration if the format
  were to change in the future, no lock if (hypothetically) multiple processes wrote to it at
  once (doesn't happen in this single-process tool, but worth stating explicitly).
- **Bulk Grading: the analysis loop lives in the browser tab**, not server-side — if the tab
  is closed during the analysis phase (after all photos have been cropped), analyses not yet
  started don't run. Ones already completed remain in the inbox (persisted, not lost).
  Not a server-side queue/job: for a personal single-user tool, building one just for this
  didn't seem justified.
