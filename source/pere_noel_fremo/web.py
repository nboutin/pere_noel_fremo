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
from .defi import (
    calculate_championship_standings,
    generate_pseudo_lugeur,
    get_all_manches,
    get_manche,
    get_or_load_grille,
    is_manche_unlocked,
    validate_grille_solution,
)
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
        standings = calculate_championship_standings(db_path, target_year)
        # Repli si aucune manche agrégée
        classement = standings if standings else get_scores_classement(db_path, target_year)
        manches = get_all_manches(year=target_year, only_unlocked=False)
        return templates.TemplateResponse(
            request=request,
            name="tableau_scores.html",
            context={
                "edition": target_year,
                "classement": classement,
                "standings": standings,
                "manches": manches,
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

    def _get_lutin_and_manche_or_raise(token: str, manche_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        lutin_info = get_lutin_by_token(db_path, token)
        if not lutin_info:
            raise HTTPException(status_code=404, detail="Lien magique introuvable")

        year = lutin_info["year"]
        lutin_id = lutin_info["id"]

        presence = get_lutin_presence(db_path, lutin_id, year)
        if not presence:
            raise HTTPException(
                status_code=403,
                detail="Tu dois d'abord confirmer ta présence pour lancer le Défi du lutin.",
            )

        manche = get_manche(year=year, manche_id=manche_id)
        if manche is None:
            raise HTTPException(status_code=404, detail=f"Manche {manche_id} introuvable.")

        if not is_manche_unlocked(manche):
            raise HTTPException(
                status_code=403,
                detail=f"La manche {manche_id} n'est pas encore déverrouillée.",
            )

        return lutin_info, manche

    async def _handle_start_defi(token: str, manche_id: int = 1) -> JSONResponse:
        lutin_info, _manche = _get_lutin_and_manche_or_raise(token, manche_id)
        year = lutin_info["year"]
        lutin_id = lutin_info["id"]

        pseudo = generate_pseudo_lugeur(lutin_id, year)
        score_entry = get_or_create_score_defi(db_path, lutin_id, year, pseudo, manche_id=manche_id)
        if score_entry.get("solved"):
            raise HTTPException(
                status_code=400,
                detail=f"La manche {manche_id} a déjà été résolue (essai unique officiel).",
            )

        updated = start_score_defi(db_path, lutin_id, year, manche_id=manche_id)
        return JSONResponse(
            {
                "ok": True,
                "manche_id": manche_id,
                "pseudo_lugeur": updated.get("pseudo_lugeur", pseudo),
                "started_at": updated.get("started_at"),
                "solved": bool(updated.get("solved", 0)),
            }
        )

    async def _handle_solve_defi(token: str, payload: GrilleSolveRequest, manche_id: int = 1) -> JSONResponse:
        lutin_info, manche = _get_lutin_and_manche_or_raise(token, manche_id)
        year = lutin_info["year"]
        lutin_id = lutin_info["id"]

        is_valid = validate_grille_solution(manche, payload.solution)
        if not is_valid:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "solved": False, "detail": "La solution soumise comporte des erreurs."},
            )

        pseudo = generate_pseudo_lugeur(lutin_id, year)
        score_entry = get_or_create_score_defi(db_path, lutin_id, year, pseudo, manche_id=manche_id)
        started_at_raw = score_entry.get("started_at")

        if not started_at_raw:
            raise HTTPException(
                status_code=400,
                detail="Le Défi du lutin doit être démarré avant d'être validé.",
            )

        try:
            start_time = datetime.strptime(str(started_at_raw), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            time_diff = (now_utc - start_time).total_seconds()
            time_seconds = max(1.0, round(time_diff, 1))
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Erreur lors du calcul du temps de complétion.",
            ) from None

        updated = complete_score_defi(db_path, lutin_id, year, time_seconds=time_seconds, manche_id=manche_id)
        return JSONResponse(
            {
                "ok": True,
                "manche_id": manche_id,
                "solved": True,
                "time_seconds": updated.get("time_seconds"),
                "pseudo_lugeur": updated.get("pseudo_lugeur", pseudo),
            }
        )

    @app.post("/api/lutin/{token}/defi/start")
    async def start_defi(token: str) -> JSONResponse:
        return await _handle_start_defi(token=token, manche_id=1)

    @app.post("/api/lutin/{token}/defi/{manche_id}/start")
    async def start_defi_manche(token: str, manche_id: int) -> JSONResponse:
        return await _handle_start_defi(token=token, manche_id=manche_id)

    @app.post("/api/lutin/{token}/defi/solve")
    async def solve_defi(token: str, payload: GrilleSolveRequest) -> JSONResponse:
        return await _handle_solve_defi(token=token, payload=payload, manche_id=1)

    @app.post("/api/lutin/{token}/defi/{manche_id}/solve")
    async def solve_defi_manche(token: str, manche_id: int, payload: GrilleSolveRequest) -> JSONResponse:
        return await _handle_solve_defi(token=token, payload=payload, manche_id=manche_id)

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
