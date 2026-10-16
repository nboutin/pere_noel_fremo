"""Éléments partagés par l'application publique et l'application Admin : gabarits Jinja2 et fichiers statiques."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .defi import format_unlock_at

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_ROOT / "templates"
STATIC_DIR = PACKAGE_ROOT / "static"


def configure_web(app: FastAPI) -> Jinja2Templates:
    """Monte `/static` sur l'application et renvoie la configuration Jinja2 commune (filtre `unlock_fr`)."""
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["unlock_fr"] = format_unlock_at
    return templates
