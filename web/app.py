"""
FastAPI application entry point — replaces the retired Textual TUI (formerly ui/app.py).

Bind to 127.0.0.1 only (see main.py) — this process holds the CardTrader token and reads/writes
local files, it must never be reachable from the network.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web.deps import BASE_DIR
from web.routers import add_card, bulk_add, collection, grading, sell
from web.state import AppState


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ygo = AppState()
    yield
    await app.state.ygo.close()


app = FastAPI(title="Yu-Gi-Oh! TCG Valuer & Collection Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(collection.router)
app.include_router(add_card.router)
app.include_router(bulk_add.router)
app.include_router(grading.router)
app.include_router(sell.router)
