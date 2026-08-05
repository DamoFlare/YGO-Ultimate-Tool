"""
Grading page — port of ui/views/grading_view.py + start_grading/_run_grading/
perform_grading_search/save_graded_card_to_collection from the retired ui/app.py.

The two debug images (original + annotated-normalized) are embedded directly as base64 PNG
data URIs in the HTML response — no terminal graphics protocol, no temporary image files to
manage, scaling handled natively by the browser's own CSS. This is the whole reason this
feature moved off the TUI — see .CLAUDE/06-note-e-discrepanze.md for the two Textual/
textual-image bugs that motivated the move.
"""
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from services.grading.ai_agent import InspectorAgentError
from services.grading.geometric_agent import CardDetectionError
from web.deps import get_state, render
from web.state import AppState, image_to_data_uri

router = APIRouter()


@router.get("/grading", response_class=HTMLResponse)
async def grading_page(request: Request):
    return render(request, 
        "grading.html",
        {"request": request, "active_tab": "grading", "cards": [], "searched": False},
    )


@router.post("/grading/analyze", response_class=HTMLResponse)
async def grading_analyze(request: Request, image: UploadFile = File(...), state: AppState = Depends(get_state)):
    suffix = Path(image.filename or "upload.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await image.read())
        tmp_path = Path(tmp.name)

    try:
        result, debug_images = await state.grader.grade_card(tmp_path)
    except CardDetectionError as e:
        return render(request, 
            "_grading_result.html",
            {"request": request, "error": f"Impossibile rilevare la carta nell'immagine: {e}"},
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

    state.last_grading_result = result
    state.last_debug_images = debug_images

    return render(request, 
        "_grading_result.html",
        {
            "request": request,
            "result": result,
            "original_src": image_to_data_uri(debug_images.original),
            "annotated_src": image_to_data_uri(debug_images.annotated),
        },
    )


@router.post("/grading/search", response_class=HTMLResponse)
async def grading_search(request: Request, query: str = Form(...), state: AppState = Depends(get_state)):
    query = query.strip()
    results = await state.api.search_cards(query) if query else []
    return render(request, 
        "_grading_search_results.html",
        {"request": request, "cards": results, "searched": True},
    )


@router.post("/grading/save", response_class=HTMLResponse)
async def grading_save(
    request: Request,
    card_id: int = Form(...),
    set_code: str = Form(""),
    rarity: str = Form(""),
    qty: int = Form(1),
    state: AppState = Depends(get_state),
):
    if not state.last_grading_result:
        return HTMLResponse('<p class="result-box error">❌ Analizza prima una foto.</p>')

    results = await state.api.get_card_by_id(card_id)
    if not results:
        return HTMLResponse('<p class="result-box error">❌ Carta non trovata (rimossa dal database?).</p>')

    card = results[0]
    selected_set = next((cs for cs in card.card_sets if cs.set_code == set_code), None) if set_code else None
    qty = qty if qty > 0 else 1

    r = state.last_grading_result
    grade_breakdown = {
        "centering": r.centering_subgrade,
        "edges": r.edges_subgrade,
        "surface": r.surface_subgrade,
    }

    item = await state.add_card_to_collection(
        card, selected_set, qty, grade=r.final_grade, condition=r.condition, grade_breakdown=grade_breakdown
    )
    state.storage.save_collection(state.collection)

    return render(request, 
        "_add_feedback.html",
        {"request": request, "item": item, "card_name": card.name, "qty": qty},
    )
