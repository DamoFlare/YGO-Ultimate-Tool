"""
Bulk Add page — port of ui/views/bulk_add_view.py + perform_bulk_load/process_bulk_add_current/
process_bulk_skip/commit_bulk_collection from ui/app.py. Queue state lives on the shared
AppState (state.bulk_queue/state.bulk_index) — single global flow, see web/state.py docstring.
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from web.deps import get_state, render
from web.state import AppState, BulkQueueItem

router = APIRouter()


def _ctx(state: AppState, request: Request, flash: str = ""):
    return {
        "request": request,
        "queue": state.bulk_queue,
        "index": state.bulk_index,
        "added_count": sum(1 for i in state.bulk_queue if i.added),
        "skipped_count": sum(1 for i in state.bulk_queue if i.skipped),
        "flash": flash,
    }


@router.get("/bulk", response_class=HTMLResponse)
async def bulk_page(request: Request, state: AppState = Depends(get_state)):
    ctx = _ctx(state, request)
    # Bulk Add is reached via a button inside the "Add Card" tab, not its own nav tab
    # (see .CLAUDE/05-ui.md) — keep that tab highlighted so the nav still makes sense here.
    ctx["active_tab"] = "add"
    return render(request, "bulk_add.html", ctx)


@router.post("/bulk/load", response_class=HTMLResponse)
async def bulk_load(request: Request, codes: str = Form(...), state: AppState = Depends(get_state)):
    code_list = [c.strip() for c in codes.replace("\n", " ").split(" ") if c.strip()]
    queue = []
    for code in code_list:
        results = await state.api.search_cards(code)
        queue.append(BulkQueueItem(code, results))
    state.bulk_queue = queue
    state.bulk_index = 0
    return render(request, "_bulk_current.html", _ctx(state, request))


@router.post("/bulk/confirm", response_class=HTMLResponse)
async def bulk_confirm(
    request: Request,
    set_code: str = Form(""),
    qty: int = Form(1),
    state: AppState = Depends(get_state),
):
    if 0 <= state.bulk_index < len(state.bulk_queue):
        item = state.bulk_queue[state.bulk_index]
        if item.results:
            card = item.results[0]
            selected_set = next((cs for cs in card.card_sets if cs.set_code == set_code), None) if set_code else None
            # Staged in memory only, not yet saved to disk — matches the old TUI behavior.
            await state.add_card_to_collection(card, selected_set, qty if qty > 0 else 1)
            item.added = True
        state.bulk_index += 1
    return render(request, "_bulk_current.html", _ctx(state, request))


@router.post("/bulk/skip", response_class=HTMLResponse)
async def bulk_skip(request: Request, state: AppState = Depends(get_state)):
    if 0 <= state.bulk_index < len(state.bulk_queue):
        state.bulk_queue[state.bulk_index].skipped = True
        state.bulk_index += 1
    return render(request, "_bulk_current.html", _ctx(state, request))


@router.post("/bulk/save-all", response_class=HTMLResponse)
async def bulk_save_all(request: Request, state: AppState = Depends(get_state)):
    ok = state.storage.save_collection(state.collection)
    flash = "Collection saved!" if ok else "Error saving the collection."
    return render(request, "_bulk_current.html", _ctx(state, request, flash=flash))
