"""
Grading page — port of ui/views/grading_view.py + start_grading/_run_grading/
perform_grading_search/save_graded_card_to_collection from the retired ui/app.py.

The two debug images (original + annotated-normalized) are embedded directly as base64 PNG
data URIs in the HTML response — no terminal graphics protocol, no temporary image files to
manage, scaling handled natively by the browser's own CSS. This is the whole reason this
feature moved off the TUI — see .CLAUDE/06-note-e-discrepanze.md for the two Textual/
textual-image bugs that motivated the move.

The card outline is no longer auto-detected: the user drags 4 corner handles over the uploaded
photo (web/static/corner-picker.js) and submits their coordinates as a JSON string in the
`corners` field, alongside the image file — for a single photo (this router's /grading/analyze)
or one at a time for a whole batch (the same endpoint, called repeatedly by the bulk sequencer in
corner-picker.js). Every analyzed card lands in `state.pending_gradings` — a shared "inbox" the
single-photo and bulk flows both feed — until the user links it to a collection item via the
`/grading/pending/*` endpoints below. See .CLAUDE/07-grading.md.
"""
import json
import tempfile
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from services.grading.ai_agent import InspectorAgentError
from services.grading.geometric_agent import CardCropError
from web.deps import get_state, render
from web.state import AppState, image_to_data_uri

router = APIRouter()


def _pending_context(
    request: Request, state: AppState, flash: str = "", flash_error: bool = False, oob: bool = False
) -> Dict[str, Any]:
    pending = []
    for p in state.pending_gradings:
        thumb = p.debug_images.original.copy()
        thumb.thumbnail((90, 130))
        pending.append({"id": p.id, "filename": p.filename, "result": p.result, "thumb_src": image_to_data_uri(thumb)})
    return {"request": request, "pending": pending, "flash": flash, "flash_error": flash_error, "oob": oob}


@router.get("/grading", response_class=HTMLResponse)
async def grading_page(request: Request, state: AppState = Depends(get_state)):
    ctx = {"request": request, "active_tab": "grading"}
    ctx.update(_pending_context(request, state))
    return render(request, "grading.html", ctx)


@router.get("/grading/pending", response_class=HTMLResponse)
async def grading_pending(request: Request, state: AppState = Depends(get_state)):
    return render(request, "_grading_pending.html", _pending_context(request, state))


@router.get("/grading/pending/{pending_id}/link", response_class=HTMLResponse)
async def grading_pending_link(request: Request, pending_id: int):
    return render(request, "_grading_pending_link.html", {"request": request, "pending_id": pending_id})


@router.post("/grading/pending/{pending_id}/discard", response_class=HTMLResponse)
async def grading_pending_discard(request: Request, pending_id: int, state: AppState = Depends(get_state)):
    removed = state.remove_pending_grading(pending_id)
    if removed:
        return render(request,
            "_grading_pending.html",
            _pending_context(request, state, flash="🗑️ Rimossa dalla lista (nessuna modifica alla collezione)."),
        )
    return render(request,
        "_grading_pending.html",
        _pending_context(request, state, flash="❌ Voce non trovata (già rimossa?).", flash_error=True),
    )


@router.post("/grading/analyze", response_class=HTMLResponse)
async def grading_analyze(
    request: Request,
    image: UploadFile = File(...),
    corners: str = Form(...),
    state: AppState = Depends(get_state),
):
    try:
        corner_points = json.loads(corners)
        if not (isinstance(corner_points, list) and len(corner_points) == 4):
            raise ValueError("expected 4 points")
    except (json.JSONDecodeError, ValueError):
        return render(request,
            "_grading_result.html",
            {"request": request, "error": "Ritaglia la carta trascinando i 4 angoli prima di analizzare."},
        )

    filename = image.filename or "upload.jpg"
    suffix = Path(filename).suffix or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await image.read())
        tmp_path = Path(tmp.name)

    try:
        result, debug_images = await state.grader.grade_card(tmp_path, corner_points)
    except CardCropError as e:
        return render(request,
            "_grading_result.html",
            {"request": request, "error": f"Ritaglio non valido: {e}"},
        )
    except InspectorAgentError as e:
        return render(request, "_grading_result.html", {"request": request, "error": str(e)})
    except Exception as e:
        return render(request,
            "_grading_result.html",
            {"request": request, "error": f"Errore imprevisto durante l'analisi: {e}"},
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    state.add_pending_grading(filename, result, debug_images)

    ctx = {
        "request": request,
        "result": result,
        "original_src": image_to_data_uri(debug_images.original),
        "annotated_src": image_to_data_uri(debug_images.annotated),
    }
    # Out-of-band swap: this response updates #grading-result (the main htmx target) AND
    # #grading-pending in the same round-trip, so the new card shows up in the inbox immediately
    # without a second request. See _grading_pending.html's `oob` flag.
    ctx.update(_pending_context(request, state, oob=True))
    return render(request, "_grading_result.html", ctx)


@router.post("/grading/search", response_class=HTMLResponse)
async def grading_search(
    request: Request, query: str = Form(...), pending_id: int = Form(...), state: AppState = Depends(get_state)
):
    query = query.strip()
    results = await state.api.search_cards(query) if query else []
    return render(request,
        "_grading_search_results.html",
        {"request": request, "cards": results, "searched": True, "pending_id": pending_id},
    )


@router.post("/grading/save", response_class=HTMLResponse)
async def grading_save(
    request: Request,
    pending_id: int = Form(...),
    card_id: int = Form(...),
    set_code: str = Form(""),
    rarity: str = Form(""),
    qty: int = Form(1),
    state: AppState = Depends(get_state),
):
    pending = state.get_pending_grading(pending_id)
    if pending is None:
        return render(request,
            "_grading_pending.html",
            _pending_context(request, state, flash="❌ Voce non trovata (già collegata o rimossa?).", flash_error=True),
        )

    results = await state.api.get_card_by_id(card_id)
    if not results:
        return render(request,
            "_grading_pending.html",
            _pending_context(request, state, flash="❌ Carta non trovata (rimossa dal database?).", flash_error=True),
        )

    card = results[0]
    selected_set = next((cs for cs in card.card_sets if cs.set_code == set_code), None) if set_code else None
    qty = qty if qty > 0 else 1

    r = pending.result
    grade_breakdown = {
        "centering": r.centering_subgrade,
        "edges": r.edges_subgrade,
        "corners": r.corners_subgrade,
        "surface": r.surface_subgrade,
    }

    await state.add_card_to_collection(
        card, selected_set, qty, grade=r.final_grade, condition=r.condition, grade_breakdown=grade_breakdown
    )
    state.storage.save_collection(state.collection)
    state.remove_pending_grading(pending_id)

    flash = f"✅ {card.name} aggiunta all'inventario con grade {r.final_grade:.1f}/10 ({r.condition})."
    return render(request, "_grading_pending.html", _pending_context(request, state, flash=flash))
