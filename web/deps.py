"""Shared FastAPI dependencies: the Jinja2 template environment and access to the shared AppState."""
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from web.state import AppState

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def get_state(request: Request) -> AppState:
    return request.app.state.ygo


def render(request: Request, name: str, context: dict) -> Response:
    """Wraps Jinja2Templates.TemplateResponse's current signature (request is a required
    explicit positional argument as of Starlette >=... this repo pins no upper bound, so keep
    this helper as the one place to fix if that signature changes again)."""
    return templates.TemplateResponse(request, name, context)
