"""
Sell on CardTrader — bulk and single-card share this exact same staging/review flow (a flat,
id-keyed list of SellStagingItem rows, one per staged stack — see web/state.py), the same
architectural pattern as the Grading module's pending_gradings inbox (web/routers/grading.py):
every row is independently addressable/actionable, so "sell one card" is simply "stage exactly
one row," not a separate code path.

Design decisions this router implements (see .claude/06-notes-and-discrepancies.md for the full
rationale, discussed and confirmed with the user before implementation):
- A CardTrader blueprint match is resolved once and persisted onto CollectionItem
  (cardtrader_blueprint_id/cardtrader_blueprint_image_url) — never silently re-guessed after
  that, unlike find_real_prices' pricing match (see services/cardtrader_api.py).
- Condition is never assumed for ungraded cards — the staging form requires an explicit choice.
- Every staged row shows the resolved blueprint's own image_url so the user can visually catch a
  wrong match before a real listing goes live.
- Idempotency is local-only: before staging or confirming, check services/storage.py's
  `listings` table for an existing active listing on that stack.
- No CardTrader webhooks exist — order/sale status is only ever updated via the manual
  /sell/poll-orders action below, never automatically.
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response

import config
from models import Listing
from services.cardtrader_api import CardTraderAPIError
from web.deps import get_state, render
from web.state import AppState

router = APIRouter()


def _suggested_price(item, condition: str) -> float:
    """Suggested listing price for a given condition — the app's own displayed value for that
    condition, undercut by config.SELL_SUGGESTED_PRICE_DISCOUNT. Purely a pre-filled starting
    point in the staging form (web/templates/_sell_staging.html) — never enforced, the price
    input stays freely editable."""
    return round(item.get_price_for_condition(condition) * (1 - config.SELL_SUGGESTED_PRICE_DISCOUNT), 2)


def _sell_context(request: Request, state: AppState, flash: str = "", flash_error: bool = False) -> dict:
    listings_view = []
    for listing in state.storage.load_listings():
        item = next((i for i in state.collection if i.row_id == listing.collection_row_id), None)
        listings_view.append({"listing": listing, "item": item})

    # Per staged row, the suggested price for EACH of the 5 condition buckets (not just the
    # currently-selected one) — embedded client-side (web/static/sell.js) so switching the
    # condition <select> re-fills the price <input> without a round-trip to the server.
    suggested_prices = {}
    for s in state.sell_staging:
        item = next((i for i in state.collection if i.row_id == s.collection_row_id), None)
        if item is not None:
            suggested_prices[s.id] = {cond: _suggested_price(item, cond) for cond in config.CARDTRADER_SELL_CONDITION}

    return {
        "request": request,
        "staging": state.sell_staging,
        "suggested_prices": suggested_prices,
        "listings": listings_view,
        "flash": flash,
        "flash_error": flash_error,
        "config": config,  # exposes config.CARDTRADER_SELL_LANGUAGES to _sell_staging.html
    }


@router.get("/sell", response_class=HTMLResponse)
async def sell_page(request: Request, state: AppState = Depends(get_state)):
    ctx = {"request": request, "active_tab": "sell"}
    ctx.update(_sell_context(request, state))
    return render(request, "sell.html", ctx)


@router.post("/sell/stage")
async def sell_stage(
    row_ids: List[int] = Form(default=[]),
    row_id: Optional[int] = Form(default=None),
    state: AppState = Depends(get_state),
):
    """Stages N rows — shared by the Collection page's bulk checkbox selection (`row_ids`,
    repeated form field) and its per-row single-card button (`row_id`, one scalar)."""
    ids = list(dict.fromkeys(list(row_ids) + ([row_id] if row_id is not None else [])))

    for rid in ids:
        item = next((i for i in state.collection if i.row_id == rid), None)
        if item is None:
            continue
        if state.find_staging_item_by_row(rid) is not None:
            continue  # already staged, no-op (idempotency within this session)
        if state.storage.get_active_listing_for_row(rid) is not None:
            continue  # already has an active listing, no-op (idempotency vs local listings)

        staging = state.add_staging_item(rid)
        staging.name = item.name
        staging.set_code = item.set_code
        staging.rarity = item.rarity
        staging.collection_quantity = item.quantity
        staging.quantity = item.quantity
        staging.condition = item.condition or ""  # never default ungraded cards to NM
        if staging.condition:
            # Graded card, condition already known — pre-fill the suggested price too (an
            # ungraded card gets its price auto-filled client-side once the user picks a
            # condition, see web/static/sell.js).
            staging.price = _suggested_price(item, staging.condition)

        if item.cardtrader_blueprint_id is not None:
            # Resolved once before (either previously staged, or via a prior sell attempt) —
            # never re-guess it.
            staging.blueprint_id = item.cardtrader_blueprint_id
            staging.blueprint_image_url = item.cardtrader_blueprint_image_url
        else:
            result = await state.cardtrader.resolve_blueprint_for_sale(item.set_code, item.rarity)
            if result["status"] == "resolved":
                bp = result["blueprint"]
                staging.blueprint_id = bp["id"]
                staging.blueprint_image_url = bp["image_url"]
                staging.blueprint_name = bp["name"]
                item.cardtrader_blueprint_id = bp["id"]
                item.cardtrader_blueprint_image_url = bp["image_url"]
                state.storage.save_collection(state.collection)
            elif result["status"] == "ambiguous":
                staging.candidates = result["candidates"]
            elif result["status"] == "not_found":
                staging.error = "No match found on CardTrader for this card — it can't be listed for sale."
            else:
                staging.error = f"Errore durante la risoluzione: {result.get('message', 'sconosciuto')}"

    # htmx: ajax POST, then full-page navigate to the review page.
    return Response(status_code=200, headers={"HX-Redirect": "/sell"})


@router.post("/sell/staging/{staging_id}/resolve", response_class=HTMLResponse)
async def sell_resolve(
    request: Request, staging_id: int, blueprint_id: int = Form(...), state: AppState = Depends(get_state)
):
    staging = state.get_staging_item(staging_id)
    if staging is None:
        return render(request, "_sell_page_content.html", _sell_context(request, state, flash="Entry not found.", flash_error=True))

    chosen = next((c for c in staging.candidates if c["id"] == blueprint_id), None)
    if chosen is None:
        return render(request, "_sell_page_content.html", _sell_context(request, state, flash="Invalid candidate.", flash_error=True))

    staging.blueprint_id = chosen["id"]
    staging.blueprint_image_url = chosen["image_url"]
    staging.blueprint_name = chosen["name"]
    staging.candidates = []
    staging.error = None

    item = next((i for i in state.collection if i.row_id == staging.collection_row_id), None)
    if item is not None:
        item.cardtrader_blueprint_id = chosen["id"]
        item.cardtrader_blueprint_image_url = chosen["image_url"]
        state.storage.save_collection(state.collection)

    return render(request, "_sell_page_content.html", _sell_context(request, state))


@router.post("/sell/staging/{staging_id}/remove", response_class=HTMLResponse)
async def sell_remove(request: Request, staging_id: int, state: AppState = Depends(get_state)):
    state.remove_staging_item(staging_id)
    return render(request, "_sell_page_content.html", _sell_context(request, state))


@router.post("/sell/confirm", response_class=HTMLResponse)
async def sell_confirm(request: Request, state: AppState = Depends(get_state)):
    """
    Reads raw form data (not typed Form(...) params) since field names are dynamic per staged
    row (condition_{id}/price_{id}/quantity_{id}) — the one deliberate exception to this app's
    otherwise-typed-Form convention, needed because the staging table has a variable row count.
    Partial-failure tolerant: one bad/erroring row stays staged with its error shown, the rest
    of the batch still gets created.
    """
    form = await request.form()
    created = skipped = failed = 0

    for staging in list(state.sell_staging):
        if staging.blueprint_id is None or staging.candidates:
            continue  # genuinely unresolved rows (no blueprint yet / still ambiguous) — skip

        # A leftover error from a PREVIOUS failed confirm attempt (bad input, or a CardTrader
        # error) must not permanently lock this row out of ever being retried — clear it and
        # re-validate fresh on every confirm attempt.
        staging.error = None

        condition = str(form.get(f"condition_{staging.id}", "")).strip().upper()
        price_raw = str(form.get(f"price_{staging.id}", "")).strip()
        quantity_raw = str(form.get(f"quantity_{staging.id}", "")).strip()
        language = str(form.get(f"language_{staging.id}", "")).strip().lower()

        if condition not in config.CARDTRADER_SELL_CONDITION:
            staging.error = "Select a condition."
            failed += 1
            continue
        if language not in dict(config.CARDTRADER_SELL_LANGUAGES):
            # Lower stakes than condition/blueprint (a wrong language doesn't misrepresent the
            # physical card, just its printed language) — fall back rather than block the row.
            language = config.DEFAULT_SELL_LANGUAGE
        try:
            price = float(price_raw.replace(",", "."))
            quantity = int(quantity_raw)
            if price <= 0 or quantity <= 0:
                raise ValueError("price/quantity must be positive")
        except ValueError:
            staging.error = "Invalid price or quantity."
            failed += 1
            continue

        if state.storage.get_active_listing_for_row(staging.collection_row_id) is not None:
            # Closes the window between staging and confirming: someone else (or another tab)
            # could have created a listing for this stack in the meantime.
            state.remove_staging_item(staging.id)
            skipped += 1
            continue

        try:
            response = await state.cardtrader.create_listing(staging.blueprint_id, price, quantity, condition, language=language)
        except CardTraderAPIError as e:
            staging.error = f"CardTrader error: {e.body}"
            failed += 1
            continue

        now = datetime.now(timezone.utc).isoformat()
        listing = Listing(
            collection_row_id=staging.collection_row_id,
            cardtrader_blueprint_id=staging.blueprint_id,
            cardtrader_product_id=response.get("id"),
            condition=condition,
            language=language,
            price_eur=price,
            quantity=quantity,
            status=config.LISTING_STATUS_ACTIVE,
            created_at=now,
            updated_at=now,
        )
        state.storage.create_listing(listing)
        state.remove_staging_item(staging.id)
        created += 1

    parts = [f"✅ {created} listings created" if created else "No listings created"]
    if skipped:
        parts.append(f"{skipped} already for sale (skipped)")
    if failed:
        parts.append(f"{failed} need fixing")
    flash = ", ".join(parts) + "."

    return render(request, "_sell_page_content.html", _sell_context(request, state, flash=flash, flash_error=(created == 0 and failed > 0)))


@router.post("/sell/listings/{listing_id}/cancel", response_class=HTMLResponse)
async def sell_cancel_listing(request: Request, listing_id: int, state: AppState = Depends(get_state)):
    listing = next((l for l in state.storage.load_listings() if l.id == listing_id), None)
    if listing is None:
        return render(request, "_sell_page_content.html", _sell_context(request, state, flash="Listing not found.", flash_error=True))

    try:
        if listing.cardtrader_product_id is not None:
            await state.cardtrader.delete_listing(listing.cardtrader_product_id)
    except CardTraderAPIError as e:
        return render(request,
            "_sell_page_content.html",
            _sell_context(request, state, flash=f"Error while cancelling: {e.body}", flash_error=True),
        )

    listing.status = config.LISTING_STATUS_CANCELLED
    listing.updated_at = datetime.now(timezone.utc).isoformat()
    state.storage.update_listing(listing)
    return render(request, "_sell_page_content.html", _sell_context(request, state, flash="Listing cancelled."))


@router.post("/sell/listings/sync-prices", response_class=HTMLResponse)
async def sell_sync_prices(request: Request, state: AppState = Depends(get_state)):
    """
    Push each active listing's price back in line with the collection's current displayed price
    for that condition (minus config.SELL_SUGGESTED_PRICE_DISCOUNT) via PUT /products/:id.
    Needed because a listing's price is a one-time snapshot taken at creation — it does NOT track
    changes to the underlying CollectionItem pricing (e.g. after /collection/refresh-prices, or
    after a pricing bug fix like the one that motivated adding this route in the first place, see
    .claude/06-notes-and-discrepancies.md). Tolerant to per-listing failures, same pattern as
    /sell/confirm.
    """
    collection_by_row = {i.row_id: i for i in state.collection}
    updated = skipped = failed = 0

    for listing in state.storage.load_listings(status=config.LISTING_STATUS_ACTIVE):
        item = collection_by_row.get(listing.collection_row_id)
        if item is None or listing.cardtrader_product_id is None:
            skipped += 1
            continue

        correct_price = _suggested_price(item, listing.condition)
        if abs(correct_price - listing.price_eur) < 0.01:
            skipped += 1
            continue

        try:
            await state.cardtrader.update_listing_price(listing.cardtrader_product_id, correct_price)
        except CardTraderAPIError:
            failed += 1
            continue

        listing.price_eur = correct_price
        listing.updated_at = datetime.now(timezone.utc).isoformat()
        state.storage.update_listing(listing)
        updated += 1

    parts = [f"🔄 {updated} listings updated" if updated else "No listings to update"]
    if skipped:
        parts.append(f"{skipped} already in sync")
    if failed:
        parts.append(f"{failed} failed")
    flash = ", ".join(parts) + "."
    return render(request, "_sell_page_content.html", _sell_context(request, state, flash=flash, flash_error=(failed > 0 and updated == 0)))


@router.post("/sell/poll-orders", response_class=HTMLResponse)
async def sell_poll_orders(request: Request, state: AppState = Depends(get_state)):
    """
    Manual-only trigger (no CardTrader webhooks exist). GET /orders' response shape is
    unconfirmed beyond "200 with an empty list" (verified live, no real orders exist yet) — this
    looks for a product id under a couple of plausible key paths defensively, and must be
    revisited once a real order actually appears (see .claude/06-notes-and-discrepancies.md).
    Does NOT touch CollectionItem.quantity — reconciling a sale against owned quantity is an
    explicitly deferred known limitation.
    """
    try:
        orders = await state.cardtrader.list_orders()
    except CardTraderAPIError as e:
        return render(request,
            "_sell_page_content.html",
            _sell_context(request, state, flash=f"Error checking orders: {e.body}", flash_error=True),
        )

    sold_product_ids = set()
    for order in orders:
        for line in order.get("order_items", order.get("items", [])):
            pid = line.get("product_id") or line.get("id")
            if pid is not None:
                sold_product_ids.add(pid)

    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    for listing in state.storage.load_listings(status=config.LISTING_STATUS_ACTIVE):
        if listing.cardtrader_product_id in sold_product_ids:
            listing.status = config.LISTING_STATUS_SOLD
            listing.sold_at = now
            listing.updated_at = now
            state.storage.update_listing(listing)
            updated += 1

    flash = f"🔄 {updated} listings are now marked sold." if updated else "🔄 No new sales detected."
    return render(request, "_sell_page_content.html", _sell_context(request, state, flash=flash))
