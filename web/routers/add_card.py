"""
Add Card page — port of ui/views/add_card_view.py + perform_card_search/
add_selected_card_to_collection from ui/app.py.

Simplification enabled by the web paradigm: the old TUI needed a stateful two-step "select
card, then select set" flow because the UI could only show one OptionList's results at a time.
Here, a single search response can render every found card together with all of its sets
inline (each set's own "Add" form carries card_id + set_code directly) — no server-side
"currently selected" state needed at all.
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from web.deps import get_state, render
from web.state import AppState

router = APIRouter()


@router.get("/add", response_class=HTMLResponse)
async def add_card_page(request: Request):
    return render(request, 
        "add_card.html",
        {"request": request, "active_tab": "add", "cards": [], "searched": False},
    )


@router.post("/add/search", response_class=HTMLResponse)
async def add_card_search(request: Request, query: str = Form(...), state: AppState = Depends(get_state)):
    query = query.strip()
    results = await state.api.search_cards(query) if query else []
    return render(request, 
        "_add_results.html",
        {"request": request, "cards": results, "searched": True},
    )


@router.post("/add/confirm", response_class=HTMLResponse)
async def add_card_confirm(
    request: Request,
    card_id: int = Form(...),
    set_code: str = Form(""),
    rarity: str = Form(""),
    qty: int = Form(1),
    state: AppState = Depends(get_state),
):
    results = await state.api.get_card_by_id(card_id)
    if not results:
        return HTMLResponse('<p class="result-box error">❌ Card not found (removed from the database?).</p>')

    card = results[0]
    selected_set = next((cs for cs in card.card_sets if cs.set_code == set_code), None) if set_code else None
    qty = qty if qty > 0 else 1

    item = await state.add_card_to_collection(card, selected_set, qty)
    state.storage.save_collection(state.collection)

    return render(request, 
        "_add_feedback.html",
        {"request": request, "item": item, "card_name": card.name, "qty": qty},
    )
