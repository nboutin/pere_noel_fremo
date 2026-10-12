from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .database import (
    complete_score_defi,
    get_beneficiaire_for_lutin,
    get_edition_status,
    get_latest_edition_year,
    get_lutin_presence,
    get_or_create_score_defi,
    get_scores_classement,
    set_lutin_presence,
    start_score_defi,
)
from .defi import generate_pseudo_lugeur, get_or_load_grille, validate_grille_solution
from .tokens import get_lutin_by_token

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "res" / "fremo.db"
TEMPLATES_DIR = PACKAGE_ROOT / "templates"
STATIC_DIR = PACKAGE_ROOT / "static"


class PresenceRequest(BaseModel):
    present: bool


class GrilleSolveRequest(BaseModel):
    solution: dict[str, Any]


def create_app(db_path: Path | str = DEFAULT_DB_PATH) -> FastAPI:
    """Crée l'application FastAPI pour l'Espace Lutin et les services festifs."""
    app = FastAPI(title="Père Noël de la Frémo - Espace Lutin")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/scores", response_class=HTMLResponse)
    @app.get("/scores/{year}", response_class=HTMLResponse)
    async def get_scores_page(request: Request, year: int | None = None) -> Any:
        target_year = year if year is not None else get_latest_edition_year(db_path)
        classement = get_scores_classement(db_path, target_year)
        return templates.TemplateResponse(
            request=request,
            name="tableau_scores.html",
            context={
                "edition": target_year,
                "classement": classement,
                "my_pseudo": None,
            },
        )

    @app.get("/lutin/{token}", response_class=HTMLResponse)
    async def get_espace_lutin(request: Request, token: str) -> Any:
        lutin_info = get_lutin_by_token(db_path, token)
        if not lutin_info:
            return templates.TemplateResponse(
                request=request,
                name="erreur_404.html",
                status_code=404,
            )

        year = lutin_info["year"]
        lutin_id = lutin_info["id"]
        presence = get_lutin_presence(db_path, lutin_id, year)
        status = get_edition_status(db_path, year) or "draft"
        is_locked = status in ("drawn", "revealed")

        # Pseudo et score du Défi de la luge
        pseudo = generate_pseudo_lugeur(lutin_id, year)
        score_info = get_or_create_score_defi(db_path, lutin_id, year, pseudo)
        grille = get_or_load_grille(year)

        # Bénéficiaire pour la Carte à gratter (si tirage scellé)
        beneficiaire = None
        if status in ("drawn", "revealed"):
            beneficiaire = get_beneficiaire_for_lutin(db_path, lutin_id, year)

        # Tableau des scores pour l'édition
        classement = get_scores_classement(db_path, year)

        return templates.TemplateResponse(
            request=request,
            name="espace_lutin.html",
            context={
                "lutin": lutin_info,
                "edition": year,
                "presence": presence,
                "is_locked": is_locked,
                "status": status,
                "score_info": score_info,
                "pseudo_lugeur": pseudo,
                "grille": grille,
                "beneficiaire": beneficiaire,
                "classement": classement,
            },
        )

    @app.post("/api/lutin/{token}/presence")
    async def post_presence(token: str, payload: PresenceRequest) -> JSONResponse:
        lutin_info = get_lutin_by_token(db_path, token)
        if not lutin_info:
            raise HTTPException(status_code=404, detail="Lien magique introuvable")

        year = lutin_info["year"]
        status = get_edition_status(db_path, year) or "draft"
        if status in ("drawn", "revealed"):
            raise HTTPException(
                status_code=403,
                detail="Le tirage au sort a été effectué, le statut de présence est verrouillé.",
            )

        set_lutin_presence(db_path, lutin_info["id"], year, payload.present)
        return JSONResponse({"ok": True, "present": payload.present})

    @app.post("/api/lutin/{token}/defi/start")
    async def start_defi(token: str) -> JSONResponse:
        lutin_info = get_lutin_by_token(db_path, token)
        if not lutin_info:
            raise HTTPException(status_code=404, detail="Lien magique introuvable")

        year = lutin_info["year"]
        lutin_id = lutin_info["id"]

        presence = get_lutin_presence(db_path, lutin_id, year)
        if not presence:
            raise HTTPException(
                status_code=403,
                detail="Tu dois d'abord confirmer ta présence pour lancer le Défi de la luge.",
            )

        pseudo = generate_pseudo_lugeur(lutin_id, year)
        get_or_create_score_defi(db_path, lutin_id, year, pseudo)
        updated = start_score_defi(db_path, lutin_id, year)

        return JSONResponse(
            {
                "ok": True,
                "pseudo_lugeur": updated.get("pseudo_lugeur", pseudo),
                "started_at": updated.get("started_at"),
                "solved": bool(updated.get("solved", 0)),
            }
        )

    @app.post("/api/lutin/{token}/defi/solve")
    async def solve_defi(token: str, payload: GrilleSolveRequest) -> JSONResponse:
        lutin_info = get_lutin_by_token(db_path, token)
        if not lutin_info:
            raise HTTPException(status_code=404, detail="Lien magique introuvable")

        year = lutin_info["year"]
        lutin_id = lutin_info["id"]

        presence = get_lutin_presence(db_path, lutin_id, year)
        if not presence:
            raise HTTPException(status_code=403, detail="Présence non confirmée.")

        grille = get_or_load_grille(year)
        is_valid = validate_grille_solution(grille, payload.solution)
        if not is_valid:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "solved": False, "detail": "La solution soumise comporte des erreurs."},
            )

        # Calcul du temps écoulé côté serveur
        pseudo = generate_pseudo_lugeur(lutin_id, year)
        score_entry = get_or_create_score_defi(db_path, lutin_id, year, pseudo)
        started_at_raw = score_entry.get("started_at")

        if not started_at_raw:
            raise HTTPException(
                status_code=400,
                detail="Le Défi de la luge doit être démarré avant d'être validé.",
            )

        try:
            # SQLite CURRENT_TIMESTAMP format '%Y-%m-%d %H:%M:%S'
            start_time = datetime.strptime(str(started_at_raw), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            time_diff = (now_utc - start_time).total_seconds()
            time_seconds = max(1.0, round(time_diff, 1))
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Erreur lors du calcul du temps de complétion.",
            ) from None

        updated = complete_score_defi(db_path, lutin_id, year, time_seconds=time_seconds)
        return JSONResponse(
            {
                "ok": True,
                "solved": True,
                "time_seconds": updated.get("time_seconds"),
                "pseudo_lugeur": updated.get("pseudo_lugeur", pseudo),
            }
        )

    @app.get("/api/lutin/{token}/beneficiaire")
    async def get_beneficiaire(token: str) -> JSONResponse:
        lutin_info = get_lutin_by_token(db_path, token)
        if not lutin_info:
            raise HTTPException(status_code=404, detail="Lien magique introuvable")

        year = lutin_info["year"]
        status = get_edition_status(db_path, year) or "draft"
        if status not in ("drawn", "revealed"):
            raise HTTPException(
                status_code=403,
                detail="Le tirage au sort n'a pas encore été validé pour cette édition.",
            )

        beneficiaire = get_beneficiaire_for_lutin(db_path, lutin_info["id"], year)
        if not beneficiaire:
            raise HTTPException(
                status_code=404,
                detail="Aucun bénéficiaire attribué trouvé pour ce lutin.",
            )

        return JSONResponse(
            {
                "ok": True,
                "id": beneficiaire["id"],
                "fullname": beneficiaire["fullname"],
            }
        )

    return app


# Application par défaut
app = create_app()
