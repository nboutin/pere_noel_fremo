import logging
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .config import default_db_path, resolve_res_dir
from .database import (
    abandon_score_defi,
    get_beneficiaire_for_lutin,
    get_edition_date_repas,
    get_edition_status,
    get_latest_edition_year,
    get_lutin_presence,
    get_or_assign_pseudo,
    get_pseudo_for_lutin,
    get_score_defi,
    get_scores_classement,
    init_db,
    register_solve_attempt,
    set_lutin_presence,
    start_score_defi,
)
from .defi import (
    MAX_ESSAIS_PAR_MANCHE,
    PENALITE_ESSAI_FAUX_SECONDES,
    GrilleInvalideError,
    calculate_championship_standings,
    format_unlock_at,
    get_all_manches,
    get_manche,
    get_manche_attributes,
    get_or_load_grille,
    is_manche_unlocked,
    is_solution_complete,
    validate_grille_solution,
)
from .helper import format_date_repas
from .tokens import get_lutin_by_token

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_ROOT / "templates"
STATIC_DIR = PACKAGE_ROOT / "static"

TOKEN_MASK_PATTERN = re.compile(r"((?:/api)?/lutin/)[^/\s?#]+")


def mask_token_in_text(text: str) -> str:
    """Remplace les jetons d'accès dans les motifs /lutin/<token> et /api/lutin/<token> par ***."""
    return TOKEN_MASK_PATTERN.sub(r"\g<1>***", text)


class TokenMaskingFilter(logging.Filter):
    """Filtre de journalisation masquant les jetons magiques dans les journaux uvicorn.access."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_token_in_text(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(mask_token_in_text(arg) if isinstance(arg, str) else arg for arg in record.args)
            elif isinstance(record.args, list):
                record.args = [mask_token_in_text(arg) if isinstance(arg, str) else arg for arg in record.args]
            elif isinstance(record.args, dict):
                record.args = {k: (mask_token_in_text(v) if isinstance(v, str) else v) for k, v in record.args.items()}
            elif isinstance(record.args, str):
                record.args = mask_token_in_text(record.args)
        return True


class PresenceRequest(BaseModel):
    present: bool


class GrilleSolveRequest(BaseModel):
    solution: dict[str, Any]


def create_app(
    db_path: Path | str | None = None,
    res_dir: Path | str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Crée l'application FastAPI pour l'Espace Lutin et les services festifs."""
    resolved_res_dir = Path(res_dir) if res_dir is not None else resolve_res_dir()
    resolved_db_path = Path(db_path) if db_path is not None else default_db_path(resolved_res_dir)
    init_db(resolved_db_path)
    db_path = resolved_db_path
    res_dir = resolved_res_dir
    clock_fn: Callable[[], datetime] = clock if clock is not None else (lambda: datetime.now(timezone.utc))
    app = FastAPI(title="Père Noël de la Frémo - Espace Lutin")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["unlock_fr"] = format_unlock_at

    @app.get("/", response_class=RedirectResponse)
    async def get_root() -> RedirectResponse:
        return RedirectResponse(url="/scores")

    @app.get("/scores", response_class=HTMLResponse)
    @app.get("/scores/{year}", response_class=HTMLResponse)
    async def get_scores_page(request: Request, year: int | None = None) -> Any:
        now_dt = clock_fn()
        target_year = year if year is not None else get_latest_edition_year(db_path)
        standings = calculate_championship_standings(db_path, target_year, res_dir=res_dir, now=now_dt)
        # Repli si aucune manche agrégée
        classement = standings if standings else get_scores_classement(db_path, target_year)
        manches = get_all_manches(year=target_year, res_dir=res_dir, now=now_dt, only_unlocked=False)

        def _strip_lutin_id(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [{k: v for k, v in e.items() if k != "lutin_id"} for e in entries]

        return templates.TemplateResponse(
            request=request,
            name="tableau_scores.html",
            context={
                "edition": target_year,
                "classement": _strip_lutin_id(classement),
                "standings": _strip_lutin_id(standings),
                "manches": manches,
                "my_pseudo": None,
            },
        )

    @app.get("/lutin/{token}", response_class=HTMLResponse)
    async def get_espace_lutin(request: Request, token: str, manche: int | None = None) -> Any:
        lutin_info = get_lutin_by_token(db_path, token)
        if not lutin_info:
            return templates.TemplateResponse(
                request=request,
                name="erreur_404.html",
                status_code=404,
            )

        year = lutin_info["year"]
        lutin_id = lutin_info["id"]
        now_dt = clock_fn()
        presence = get_lutin_presence(db_path, lutin_id, year)
        status = get_edition_status(db_path, year) or "draft"
        is_locked = status in ("drawn", "revealed")

        # Lecture seule : on ne génère pas de pseudo s'il n'existe pas encore
        pseudo = get_pseudo_for_lutin(db_path, lutin_id, year)

        # 1. Calendrier des manches et statuts pour ce lutin
        all_manches = get_all_manches(year=year, res_dir=res_dir, now=now_dt, only_unlocked=False)
        for m in all_manches:
            m_id = int(m["id"])
            m_score = get_score_defi(db_path, lutin_id, year, manche_id=m_id)
            m["user_score"] = m_score
            m["is_solved"] = bool(m_score.get("solved"))
            if m["is_solved"]:
                m["status_tag"] = "resolue"
            elif m_score.get("completed_at") is not None:
                m["status_tag"] = "abandonnee"
            elif m.get("is_unlocked"):
                m["status_tag"] = "disponible"
            else:
                m["status_tag"] = "verrouillee"
            m.pop("indices", None)
            m.pop("solution", None)
            if not m.get("is_unlocked"):
                m.pop("categories", None)

        # 2. Détermination de la manche active
        active_manche_id = 1
        if manche is not None and any(m["id"] == manche for m in all_manches):
            active_manche_id = manche
        else:
            # Sélectionner en priorité la première manche disponible non résolue
            dispo = next((m["id"] for m in all_manches if m["status_tag"] == "disponible"), None)
            if dispo is not None:
                active_manche_id = dispo
            elif all_manches:
                active_manche_id = all_manches[0]["id"]

        active_manche = get_manche(year=year, manche_id=active_manche_id, res_dir=res_dir, now=now_dt)
        if active_manche is None:
            active_manche = get_or_load_grille(year, res_dir=res_dir)

        active_score = get_score_defi(db_path, lutin_id, year, manche_id=active_manche_id)

        # 3. Profil championnat et classement
        standings = calculate_championship_standings(db_path, year, res_dir=res_dir, now=now_dt)
        my_standing = next(
            (entry for entry in standings if entry.get("lutin_id") == lutin_id),
            None,
        )
        leader_points = standings[0]["total_points"] if standings else 0
        my_points = my_standing["total_points"] if my_standing else 0
        gap_to_leader = max(0, leader_points - my_points) if my_standing else None

        # Préparation de la manche pour le rendu : aucun indice n'est transmis via la page HTML
        is_active_unlocked = bool(active_manche.get("is_unlocked"))
        if is_active_unlocked:
            raw_indices = list(active_manche.get("indices") or [])
            indices_count = len(raw_indices)
            try:
                attributes = get_manche_attributes(active_manche)
            except GrilleInvalideError:
                attributes = []
            display_manche = {
                "attributes": [{"key": cle, "category": categorie} for cle, categorie in attributes],
                "id": active_manche.get("id", active_manche_id),
                "title": active_manche.get("title"),
                "description": active_manche.get("description"),
                "estimated_time": active_manche.get("estimated_time"),
                "categories": active_manche.get("categories", {}),
                "unlock_at": active_manche.get("unlock_at"),
                "is_unlocked": True,
            }
        else:
            indices_count = 0
            display_manche = {
                "id": active_manche.get("id", active_manche_id),
                "title": active_manche.get("title"),
                "unlock_at": active_manche.get("unlock_at"),
                "is_unlocked": False,
            }

        # Bénéficiaire pour la Carte à gratter (si tirage scellé)
        beneficiaire = None
        if status in ("drawn", "revealed"):
            beneficiaire = get_beneficiaire_for_lutin(db_path, lutin_id, year)

        # Date du Repas de Noël
        date_repas_raw = get_edition_date_repas(db_path, year)
        date_repas_info = format_date_repas(date_repas_raw)

        classement = standings if standings else get_scores_classement(db_path, year)

        return templates.TemplateResponse(
            request=request,
            name="espace_lutin.html",
            context={
                "lutin": lutin_info,
                "edition": year,
                "date_repas_info": date_repas_info,
                "presence": presence,
                "is_locked": is_locked,
                "status": status,
                "score_info": active_score,
                "pseudo_lutin": pseudo,
                "active_manche": display_manche,
                "active_manche_id": active_manche_id,
                "indices_count": indices_count,
                "manches": all_manches,
                "standings": standings,
                "my_standing": my_standing,
                "gap_to_leader": gap_to_leader,
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

        now_dt = clock_fn()
        manche = get_manche(year=year, manche_id=manche_id, res_dir=res_dir, now=now_dt)
        if manche is None:
            raise HTTPException(status_code=404, detail=f"Manche {manche_id} introuvable.")

        if not is_manche_unlocked(manche, now=now_dt):
            raise HTTPException(
                status_code=403,
                detail=f"La manche {manche_id} n'est pas encore déverrouillée.",
            )

        return lutin_info, manche

    async def _handle_start_defi(token: str, manche_id: int = 1) -> JSONResponse:
        lutin_info, manche = _get_lutin_and_manche_or_raise(token, manche_id)
        year = lutin_info["year"]
        lutin_id = lutin_info["id"]

        # Garde : une manche incohérente ne doit jamais lancer le chronomètre.
        try:
            get_manche_attributes(manche)
        except GrilleInvalideError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"La manche {manche_id} est mal configurée et ne peut pas démarrer : {exc}",
            ) from exc

        pseudo = get_or_assign_pseudo(db_path, lutin_id, year)
        score_entry = get_score_defi(db_path, lutin_id, year, manche_id=manche_id)
        if score_entry.get("solved"):
            raise HTTPException(
                status_code=400,
                detail=f"La manche {manche_id} a déjà été résolue (essai unique officiel).",
            )
        if score_entry.get("completed_at"):
            raise HTTPException(
                status_code=400,
                detail=f"La manche {manche_id} a été abandonnée (essai unique officiel).",
            )

        updated = start_score_defi(
            db_path,
            lutin_id,
            year,
            pseudo_lutin=pseudo,
            manche_id=manche_id,
            now=clock_fn(),
        )
        assigned_pseudo = updated.get("pseudo_lutin") or pseudo
        return JSONResponse(
            {
                "ok": True,
                "manche_id": manche_id,
                "pseudo_lutin": assigned_pseudo,
                "started_at": updated.get("started_at"),
                "solved": bool(updated.get("solved", 0)),
                "indices": list(manche.get("indices") or []),
            }
        )

    async def _handle_get_indices(token: str, manche_id: int = 1) -> JSONResponse:
        lutin_info, manche = _get_lutin_and_manche_or_raise(token, manche_id)
        year = lutin_info["year"]
        lutin_id = lutin_info["id"]

        score_entry = get_score_defi(db_path, lutin_id, year, manche_id=manche_id)
        if not score_entry.get("started_at") or score_entry.get("completed_at") is not None:
            raise HTTPException(
                status_code=403,
                detail="Les indices ne sont accessibles que pendant un essai en cours.",
            )

        return JSONResponse(
            {
                "ok": True,
                "manche_id": manche_id,
                "indices": list(manche.get("indices") or []),
            }
        )

    async def _handle_solve_defi(token: str, payload: GrilleSolveRequest, manche_id: int = 1) -> JSONResponse:
        lutin_info, manche = _get_lutin_and_manche_or_raise(token, manche_id)
        year = lutin_info["year"]
        lutin_id = lutin_info["id"]

        score_entry = get_score_defi(db_path, lutin_id, year, manche_id=manche_id)

        if score_entry.get("completed_at"):
            raise HTTPException(
                status_code=400,
                detail=f"La manche {manche_id} est déjà terminée (essai unique officiel).",
            )

        if not score_entry.get("started_at"):
            raise HTTPException(
                status_code=400,
                detail="Le Défi du lutin doit être démarré avant d'être validé.",
            )

        # Seules les soumissions complètes mais erronées consomment un essai.
        # Les requêtes incomplètes/malformées sont rejetées sans incrémenter attempts.
        if not is_solution_complete(manche, payload.solution):
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "solved": False,
                    "detail": "La solution soumise est incomplète (tous les choix doivent être renseignés).",
                },
            )

        is_valid = validate_grille_solution(manche, payload.solution)

        result = register_solve_attempt(
            db_path=db_path,
            lutin_id=lutin_id,
            year=year,
            manche_id=manche_id,
            is_valid=is_valid,
            max_attempts=MAX_ESSAIS_PAR_MANCHE,
            penalty_seconds=float(PENALITE_ESSAI_FAUX_SECONDES),
            now=clock_fn(),
        )

        if result.get("already_completed"):
            raise HTTPException(
                status_code=400,
                detail=f"La manche {manche_id} est déjà terminée (essai unique officiel).",
            )

        pseudo = score_entry.get("pseudo_lutin") or get_pseudo_for_lutin(db_path, lutin_id, year) or "Lutin"

        if result.get("solved"):
            return JSONResponse(
                {
                    "ok": True,
                    "manche_id": manche_id,
                    "solved": True,
                    "attempts": result["attempts"],
                    "time_seconds": result["time_seconds"],
                    "pseudo_lutin": pseudo,
                }
            )

        attempts = int(result["attempts"])
        essais_restants = int(result["essais_restants"])
        sealed = bool(result.get("sealed", False))

        if sealed:
            detail = f"Nombre maximal d'essais atteint ({attempts}/{MAX_ESSAIS_PAR_MANCHE}). La manche est scellée."
        else:
            penalite_acc = int(attempts * PENALITE_ESSAI_FAUX_SECONDES)
            detail = (
                f"La solution soumise comporte des erreurs. "
                f"Essais restants : {essais_restants}/{MAX_ESSAIS_PAR_MANCHE} "
                f"(pénalité accumulée : +{penalite_acc}s)."
            )

        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "solved": False,
                "attempts": attempts,
                "essais_restants": essais_restants,
                "penalite_secondes": PENALITE_ESSAI_FAUX_SECONDES,
                "detail": detail,
            },
        )

    async def _handle_abandon_defi(token: str, manche_id: int = 1) -> JSONResponse:
        lutin_info, _manche = _get_lutin_and_manche_or_raise(token, manche_id)
        year = lutin_info["year"]
        lutin_id = lutin_info["id"]

        score_entry = get_score_defi(db_path, lutin_id, year, manche_id=manche_id)
        if score_entry.get("completed_at"):
            raise HTTPException(
                status_code=400,
                detail=f"La manche {manche_id} est déjà terminée (essai unique officiel).",
            )
        if not score_entry.get("started_at"):
            raise HTTPException(
                status_code=400,
                detail="Le Défi du lutin doit être démarré avant de pouvoir être abandonné.",
            )

        updated = abandon_score_defi(db_path, lutin_id, year, manche_id=manche_id, now=clock_fn())
        pseudo = score_entry.get("pseudo_lutin") or get_pseudo_for_lutin(db_path, lutin_id, year) or "Lutin"
        abandoned_pseudo = updated.get("pseudo_lutin") or pseudo
        return JSONResponse(
            {
                "ok": True,
                "manche_id": manche_id,
                "abandoned": True,
                "pseudo_lutin": abandoned_pseudo,
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

    @app.post("/api/lutin/{token}/defi/abandon")
    async def abandon_defi(token: str) -> JSONResponse:
        return await _handle_abandon_defi(token=token, manche_id=1)

    @app.post("/api/lutin/{token}/defi/{manche_id}/abandon")
    async def abandon_defi_manche(token: str, manche_id: int) -> JSONResponse:
        return await _handle_abandon_defi(token=token, manche_id=manche_id)

    @app.get("/api/lutin/{token}/defi/indices")
    async def get_defi_indices(token: str) -> JSONResponse:
        return await _handle_get_indices(token=token, manche_id=1)

    @app.get("/api/lutin/{token}/defi/{manche_id}/indices")
    async def get_defi_manche_indices(token: str, manche_id: int) -> JSONResponse:
        return await _handle_get_indices(token=token, manche_id=manche_id)

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
