"""
Collection & Valuation page — port of the old ui/views/collection_view.py + the collection-
related handlers from ui/app.py (refresh_all_prices, delete_selected_card, export_to_csv).
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse

from web.deps import get_state, render
from web.state import AppState

router = APIRouter()

SORT_EXTRACTORS = {
    "id": lambda item: item.id,
    "name": lambda item: item.name.lower(),
    "set_code": lambda item: item.set_code.lower(),
    "rarity": lambda item: (item.rarity or "Standard").lower(),
    "grade": lambda item: item.grade if item.grade is not None else -1.0,
    "quantity": lambda item: item.quantity,
    "base_price": lambda item: item.base_price,
    "ex": lambda item: item.get_price_for_condition("EX"),
    "gd": lambda item: item.get_price_for_condition("GD"),
    "lp": lambda item: item.get_price_for_condition("LP"),
    "po": lambda item: item.get_price_for_condition("PO"),
    "total": lambda item: item.total_nm_price,
    "effective": lambda item: item.total_effective_price,
}


def _build_context(state: AppState, filter_text: str = "", min_price_str: str = "", sort: str = "", direction: str = "asc", flash: str = ""):
    items = state.collection
    filter_text_lower = filter_text.strip().lower()
    min_price = None
    if min_price_str.strip():
        try:
            min_price = float(min_price_str.strip().replace(",", "."))
        except ValueError:
            min_price = None

    filtered = [
        item for item in items
        if (not filter_text_lower or filter_text_lower in item.name.lower() or filter_text_lower in item.set_code.lower())
        and (min_price is None or item.base_price >= min_price)
    ]

    if sort in SORT_EXTRACTORS:
        filtered = sorted(filtered, key=SORT_EXTRACTORS[sort], reverse=(direction == "desc"))

    def next_dir(col: str) -> str:
        if sort == col and direction == "asc":
            return "desc"
        return "asc"

    return {
        "items": filtered,
        "filter_text": filter_text,
        "min_price_str": min_price_str,
        "sort": sort,
        "direction": direction,
        "next_dir": next_dir,
        "flash": flash,
        "total_unique": len(items),
        "total_pieces": sum(item.quantity for item in items),
        "total_nm_val": sum(item.total_nm_price for item in items),
        "total_ex_val": sum(item.get_price_for_condition("EX") * item.quantity for item in items),
        "total_gd_val": sum(item.get_price_for_condition("GD") * item.quantity for item in items),
        "total_lp_val": sum(item.get_price_for_condition("LP") * item.quantity for item in items),
        "total_po_val": sum(item.get_price_for_condition("PO") * item.quantity for item in items),
    }


@router.get("/", response_class=HTMLResponse)
async def collection_page(request: Request, state: AppState = Depends(get_state)):
    ctx = _build_context(state)
    ctx.update({"request": request, "active_tab": "collection"})
    return render(request, "collection.html", ctx)


@router.get("/collection/table", response_class=HTMLResponse)
async def collection_table(
    request: Request,
    q: str = "",
    min_price: str = "",
    sort: str = "",
    dir: str = "asc",
    state: AppState = Depends(get_state),
):
    ctx = _build_context(state, filter_text=q, min_price_str=min_price, sort=sort, direction=dir)
    ctx.update({"request": request})
    return render(request, "_collection_content.html", ctx)


@router.post("/collection/refresh-prices", response_class=HTMLResponse)
async def refresh_prices(request: Request, state: AppState = Depends(get_state)):
    """Re-query CardTrader for real marketplace prices on every collection item."""
    real_price_count = 0
    for item in state.collection:
        real_prices = await state.cardtrader.find_real_prices(item.set_code, item.rarity)
        if real_prices:
            item.real_condition_prices = real_prices
            item.price_source = "cardtrader"
            if "NM" in real_prices:
                item.base_price = real_prices["NM"]
            real_price_count += 1
        else:
            item.real_condition_prices = None
            item.price_source = None
    state.storage.save_collection(state.collection)

    ctx = _build_context(
        state,
        flash=f"Prezzi reali CardTrader trovati per {real_price_count}/{len(state.collection)} carte.",
    )
    ctx.update({"request": request})
    return render(request, "_collection_content.html", ctx)


@router.post("/collection/delete", response_class=HTMLResponse)
async def delete_item(
    request: Request,
    id: int = Form(...),
    set_code: str = Form(...),
    rarity: str = Form(...),
    grade: str = Form(""),
    state: AppState = Depends(get_state),
):
    grade_val = float(grade) if grade.strip() else None
    state.collection = [
        item for item in state.collection
        if not (item.id == id and item.set_code == set_code and item.rarity == rarity and item.grade == grade_val)
    ]
    state.storage.save_collection(state.collection)
    ctx = _build_context(state, flash="Carta rimossa dalla collezione.")
    ctx.update({"request": request})
    return render(request, "_collection_content.html", ctx)


@router.get("/collection/export-csv")
async def export_csv(state: AppState = Depends(get_state)):
    if not state.storage.export_to_csv(state.collection):
        return HTMLResponse("Errore durante l'esportazione CSV.", status_code=500)
    return FileResponse(str(state.storage.csv_path), filename="collection.csv", media_type="text/csv")
