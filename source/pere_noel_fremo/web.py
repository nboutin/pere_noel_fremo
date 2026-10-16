import hashlib
import hmac
import json
import logging
import urllib.parse
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anyio.from_thread
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .admin import get_admin_edition_summary
from .config import (
    PARIS_TZ,
    default_db_path,
    get_admin_password,
    get_admin_session_secret,
    resolve_res_dir,
)
from .database import (
    get_beneficiaire_for_lutin,
    get_edition_date_repas,
    get_lutin_presence,
    get_lutin_pseudo,
    get_scores_classement,
    init_db,
)
from .defi import (
    GrilleInvalideError,
    calculate_championship_standings,
    format_unlock_at,
    get_all_manches,
    get_manche,
    get_manche_attributes,
    get_or_load_grille,
)
from .edition import annee_courante, est_scellee, statut
from .helper import format_date_repas
from .parcours import StatutManche, StatutParcours, StatutSoumission, abandonner, demarrer, indices, soumettre
from .parcours import etat as etat_parcours
from .presence import StatutPresence, confirmer
from .tokens import get_lutin_by_token

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_ROOT / "templates"
STATIC_DIR = PACKAGE_ROOT / "static"

SESSION_COOKIE_NAME = "admin_session"
SESSION_DURATION_SECONDS = 7200
MIN_SESSION_SECRET_BYTES = 32

logger = logging.getLogger(__name__)


def is_tailscale_funnel_request(request: Request) -> bool:
    if request.headers.get("tailscale-funnel-request") == "?1":
        return True
    host = request.headers.get("host", "")
    if ":10000" in host:
        return True
    xf_host = request.headers.get("x-forwarded-host", "")
    return ":10000" in xf_host


def create_session_token(secret: str, timestamp: int) -> str:
    signature = hmac.new(
        secret.encode("utf-8"),
        str(timestamp).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{timestamp}.{signature}"


def verify_session_token(token: str, secret: str, now: int, max_age: int = SESSION_DURATION_SECONDS) -> bool:
    if not token or "." not in token:
        return False
    parts = token.split(".", 1)
    if len(parts) != 2:
        return False
    ts_str, signature = parts
    try:
        ts = int(ts_str)
    except ValueError:
        return False

    expected_sig = hmac.new(
        secret.encode("utf-8"),
        ts_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        return False

    return not ((now - ts) > max_age or ts > (now + 300))


class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 900) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = {}

    def is_blocked(self, ip: str, now: float) -> bool:
        self._cleanup(ip, now)
        return len(self._attempts.get(ip, [])) >= self.max_attempts

    def record_failure(self, ip: str, now: float) -> None:
        self._cleanup(ip, now)
        self._attempts.setdefault(ip, []).append(now)

    def record_success(self, ip: str) -> None:
        self._attempts.pop(ip, None)

    def reset(self) -> None:
        self._attempts.clear()

    def _cleanup(self, ip: str, now: float) -> None:
        if ip in self._attempts:
            self._attempts[ip] = [t for t in self._attempts[ip] if now - t < self.window_seconds]
            if not self._attempts[ip]:
                self._attempts.pop(ip, None)


class PresenceRequest(BaseModel):
    present: bool


class GrilleSolveRequest(BaseModel):
    solution: dict[str, Any]


def create_app(
    db_path: Path | str | None = None,
    res_dir: Path | str | None = None,
    clock: Callable[[], datetime] | None = None,
    admin_password: str | None = None,
    admin_session_secret: str | None = None,
) -> FastAPI:
    """Crée l'application FastAPI pour l'Espace Lutin et les services festifs."""
    resolved_res_dir = Path(res_dir) if res_dir is not None else resolve_res_dir()
    resolved_db_path = Path(db_path) if db_path is not None else default_db_path(resolved_res_dir)
    init_db(resolved_db_path)
    db_path = resolved_db_path
    res_dir = resolved_res_dir
    clock_fn: Callable[[], datetime] = clock if clock is not None else (lambda: datetime.now(timezone.utc))

    admin_pwd = admin_password if admin_password is not None else get_admin_password(res_dir)
    session_sec = admin_session_secret if admin_session_secret is not None else get_admin_session_secret(res_dir)
    admin_enabled = session_sec is not None and len(session_sec.encode("utf-8")) >= MIN_SESSION_SECRET_BYTES
    session_secret = session_sec if admin_enabled and session_sec is not None else ""
    if not admin_enabled:
        logger.warning(
            "Espace Admin désactivé : aucun secret de session valide (%d octets minimum). "
            "Définir la clé admin_session_secret (secure_data.yml) ou la variable ADMIN_SESSION_SECRET, "
            'par exemple générée avec : python -c "import secrets; print(secrets.token_urlsafe(48))"',
            MIN_SESSION_SECRET_BYTES,
        )
    rate_limiter = LoginRateLimiter(max_attempts=5, window_seconds=900)

    app = FastAPI(title="Père Noël de la Frémo - Espace Lutin")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["unlock_fr"] = format_unlock_at

    @app.middleware("http")
    async def tailscale_funnel_guard(request: Request, call_next: Callable[[Request], Any]) -> Any:
        path = request.url.path.lower()
        if (path == "/admin" or path.startswith("/admin/")) and (
            not admin_enabled or is_tailscale_funnel_request(request)
        ):
            return templates.TemplateResponse(
                request=request,
                name="erreur_404.html",
                status_code=404,
            )
        return await call_next(request)

    @app.get("/", response_class=RedirectResponse)
    def get_root() -> RedirectResponse:
        return RedirectResponse(url="/scores")

    @app.get("/scores", response_class=HTMLResponse)
    @app.get("/scores/{year}", response_class=HTMLResponse)
    def get_scores_page(request: Request, year: int | None = None) -> Any:
        now_dt = clock_fn()
        target_year = year if year is not None else annee_courante(db_path)
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
    def get_espace_lutin(request: Request, token: str, manche: int | None = None) -> Any:
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
        edition_scellee = est_scellee(statut(db_path, year))

        # Lecture seule : on ne génère pas de pseudo s'il n'existe pas encore
        pseudo = get_lutin_pseudo(db_path, lutin_id, year)

        # 1. Calendrier des manches et statuts pour ce lutin
        all_manches = get_all_manches(year=year, res_dir=res_dir, now=now_dt, only_unlocked=False)
        etats = etat_parcours(db_path, lutin_id, year, all_manches, now_dt)
        for m, etat_manche in zip(all_manches, etats, strict=True):
            m["statut"] = etat_manche.statut.value
            m["is_solved"] = etat_manche.statut is StatutManche.RESOLUE
            m["user_score"] = {"solved": m["is_solved"], "time_seconds": etat_manche.time_seconds}
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
            a_jouer = (StatutManche.DISPONIBLE.value, StatutManche.EN_COURS.value)
            dispo = next((m["id"] for m in all_manches if m["statut"] in a_jouer), None)
            if dispo is not None:
                active_manche_id = dispo
            elif all_manches:
                active_manche_id = all_manches[0]["id"]

        active_manche = get_manche(year=year, manche_id=active_manche_id, res_dir=res_dir, now=now_dt)
        if active_manche is None:
            active_manche = get_or_load_grille(year, res_dir=res_dir)

        etat_actif = next((e for e in etats if e.manche_id == active_manche_id), None)
        if etat_actif is None:
            active_score: dict[str, Any] = {}
        else:
            # Dérivé de l'état déjà lu : solved et completed_at se déduisent du statut
            terminee = etat_actif.statut in (StatutManche.RESOLUE, StatutManche.ABANDONNEE, StatutManche.SCELLEE)
            active_score = {
                "solved": etat_actif.statut is StatutManche.RESOLUE,
                "completed_at": terminee or None,
                "started_at": etat_actif.started_at,
                "attempts": etat_actif.attempts,
                "time_seconds": etat_actif.time_seconds,
            }

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
                grille_invalide = True
            else:
                grille_invalide = False
            display_manche = {
                "grille_invalide": grille_invalide,
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
        if edition_scellee:
            beneficiaire = get_beneficiaire_for_lutin(db_path, lutin_id, year)

        # Date du Repas de Noël
        date_repas_raw = get_edition_date_repas(db_path, year)
        date_repas_info = format_date_repas(date_repas_raw, now=now_dt.astimezone(PARIS_TZ))

        classement = standings if standings else get_scores_classement(db_path, year)

        return templates.TemplateResponse(
            request=request,
            name="espace_lutin.html",
            context={
                "lutin": lutin_info,
                "edition": year,
                "date_repas_info": date_repas_info,
                "presence": presence,
                "edition_scellee": edition_scellee,
                "defi_clos": etat_actif is not None and etat_actif.statut is StatutManche.CLOSE,
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
    def post_presence(token: str, payload: PresenceRequest) -> JSONResponse:
        lutin_info = get_lutin_by_token(db_path, token)
        if not lutin_info:
            raise HTTPException(status_code=404, detail="Lien magique introuvable")

        year = lutin_info["year"]
        if confirmer(db_path, lutin_info["id"], year, payload.present) is StatutPresence.VERROUILLEE:
            raise HTTPException(
                status_code=403,
                detail="Le tirage au sort a été effectué, le statut de présence est verrouillé.",
            )

        return JSONResponse({"ok": True, "present": payload.present})

    def _refus_parcours(
        statut: StatutParcours | StatutSoumission,
        manche_id: int,
        detail: str | None = None,
        *,
        pour_indices: bool = False,
    ) -> HTTPException | None:
        """Traduit un statut de refus du Parcours ou de la Soumission en erreur HTTP (None si l'opération a abouti).

        ``pour_indices`` : la consultation des indices n'est permise que pendant un essai en cours.
        """
        if pour_indices and statut in (StatutParcours.NON_DEMARRE, StatutParcours.DEJA_TERMINEE):
            return HTTPException(
                status_code=403,
                detail="Les indices ne sont accessibles que pendant un essai en cours.",
            )
        if statut is StatutParcours.PRESENCE_REQUISE or statut is StatutSoumission.PRESENCE_REQUISE:
            return HTTPException(
                status_code=403,
                detail="Tu dois d'abord confirmer ta présence pour lancer le Défi du lutin.",
            )
        if statut is StatutParcours.MANCHE_INTROUVABLE or statut is StatutSoumission.MANCHE_INTROUVABLE:
            return HTTPException(status_code=404, detail=f"Manche {manche_id} introuvable.")
        if statut is StatutParcours.MANCHE_VERROUILLEE or statut is StatutSoumission.MANCHE_VERROUILLEE:
            return HTTPException(status_code=403, detail=f"La manche {manche_id} n'est pas encore déverrouillée.")
        if statut is StatutParcours.DEFI_CLOS or statut is StatutSoumission.DEFI_CLOS:
            return HTTPException(status_code=403, detail="Le Défi du lutin est clos depuis le Repas de Noël.")
        if statut is StatutParcours.GRILLE_INVALIDE:
            return HTTPException(
                status_code=409,
                detail=f"La manche {manche_id} est mal configurée et ne peut pas démarrer : {detail}",
            )
        if statut is StatutParcours.DEJA_RESOLUE:
            return HTTPException(
                status_code=400,
                detail=f"La manche {manche_id} a déjà été résolue (essai unique officiel).",
            )
        if statut is StatutParcours.NON_DEMARRE:
            return HTTPException(
                status_code=400,
                detail="Le Défi du lutin doit être démarré avant de pouvoir être abandonné.",
            )
        return None

    def _handle_start_defi(token: str, manche_id: int = 1) -> JSONResponse:
        lutin_info = get_lutin_by_token(db_path, token)
        if not lutin_info:
            raise HTTPException(status_code=404, detail="Lien magique introuvable")
        now_dt = clock_fn()
        manche = get_manche(year=lutin_info["year"], manche_id=manche_id, res_dir=res_dir, now=now_dt)

        resultat = demarrer(db_path, lutin_info["id"], lutin_info["year"], manche, now_dt)
        if resultat.statut is StatutParcours.DEJA_TERMINEE:
            raise HTTPException(
                status_code=400,
                detail=f"La manche {manche_id} a été abandonnée (essai unique officiel).",
            )
        refus = _refus_parcours(resultat.statut, manche_id, resultat.detail)
        if refus is not None:
            raise refus
        return JSONResponse(
            {
                "ok": True,
                "manche_id": manche_id,
                "pseudo_lutin": resultat.pseudo_lutin,
                "started_at": resultat.started_at,
                "solved": False,
                "indices": resultat.indices,
            }
        )

    def _handle_get_indices(token: str, manche_id: int = 1) -> JSONResponse:
        lutin_info = get_lutin_by_token(db_path, token)
        if not lutin_info:
            raise HTTPException(status_code=404, detail="Lien magique introuvable")
        now_dt = clock_fn()
        manche = get_manche(year=lutin_info["year"], manche_id=manche_id, res_dir=res_dir, now=now_dt)

        resultat = indices(db_path, lutin_info["id"], lutin_info["year"], manche, now_dt)
        refus = _refus_parcours(resultat.statut, manche_id, pour_indices=True)
        if refus is not None:
            raise refus
        return JSONResponse({"ok": True, "manche_id": manche_id, "indices": resultat.indices})

    def _handle_solve_defi(token: str, payload: GrilleSolveRequest, manche_id: int = 1) -> JSONResponse:
        lutin_info = get_lutin_by_token(db_path, token)
        if not lutin_info:
            raise HTTPException(status_code=404, detail="Lien magique introuvable")
        now_dt = clock_fn()
        manche = get_manche(year=lutin_info["year"], manche_id=manche_id, res_dir=res_dir, now=now_dt)

        resultat = soumettre(db_path, lutin_info["id"], lutin_info["year"], manche, payload.solution, now_dt)
        statut = resultat.statut
        if statut is StatutSoumission.DEJA_TERMINEE:
            raise HTTPException(
                status_code=400,
                detail=f"La manche {manche_id} est déjà terminée (essai unique officiel).",
            )
        if statut is StatutSoumission.NON_DEMARRE:
            raise HTTPException(status_code=400, detail="Le Défi du lutin doit être démarré avant d'être validé.")
        refus = _refus_parcours(statut, manche_id)
        if refus is not None:
            raise refus

        if statut is StatutSoumission.INCOMPLETE:
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "solved": False,
                    "detail": "La solution soumise est incomplète (tous les choix doivent être renseignés).",
                },
            )

        if statut is StatutSoumission.RESOLUE:
            return JSONResponse(
                {
                    "ok": True,
                    "manche_id": manche_id,
                    "solved": True,
                    "attempts": resultat.attempts,
                    "time_seconds": resultat.time_seconds,
                    "pseudo_lutin": resultat.pseudo_lutin or "Lutin",
                }
            )

        if statut is StatutSoumission.SCELLEE:
            detail = (
                f"Nombre maximal d'essais atteint ({resultat.attempts}/{resultat.essais_max}). La manche est scellée."
            )
        else:
            detail = (
                f"La solution soumise comporte des erreurs. "
                f"Essais restants : {resultat.essais_restants}/{resultat.essais_max} "
                f"(pénalité accumulée : +{resultat.penalite_cumulee_secondes}s)."
            )

        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "solved": False,
                "attempts": resultat.attempts,
                "essais_restants": resultat.essais_restants,
                "penalite_secondes": resultat.penalite_essai_secondes,
                "detail": detail,
            },
        )

    def _handle_abandon_defi(token: str, manche_id: int = 1) -> JSONResponse:
        lutin_info = get_lutin_by_token(db_path, token)
        if not lutin_info:
            raise HTTPException(status_code=404, detail="Lien magique introuvable")
        now_dt = clock_fn()
        manche = get_manche(year=lutin_info["year"], manche_id=manche_id, res_dir=res_dir, now=now_dt)

        resultat = abandonner(db_path, lutin_info["id"], lutin_info["year"], manche, now_dt)
        if resultat.statut is StatutParcours.DEJA_TERMINEE:
            raise HTTPException(
                status_code=400,
                detail=f"La manche {manche_id} est déjà terminée (essai unique officiel).",
            )
        refus = _refus_parcours(resultat.statut, manche_id, resultat.detail)
        if refus is not None:
            raise refus
        return JSONResponse(
            {
                "ok": True,
                "manche_id": manche_id,
                "abandoned": True,
                "pseudo_lutin": resultat.pseudo_lutin or "Lutin",
            }
        )

    @app.post("/api/lutin/{token}/defi/start")
    def start_defi(token: str) -> JSONResponse:
        return _handle_start_defi(token=token, manche_id=1)

    @app.post("/api/lutin/{token}/defi/{manche_id}/start")
    def start_defi_manche(token: str, manche_id: int) -> JSONResponse:
        return _handle_start_defi(token=token, manche_id=manche_id)

    @app.post("/api/lutin/{token}/defi/solve")
    def solve_defi(token: str, payload: GrilleSolveRequest) -> JSONResponse:
        return _handle_solve_defi(token=token, payload=payload, manche_id=1)

    @app.post("/api/lutin/{token}/defi/{manche_id}/solve")
    def solve_defi_manche(token: str, manche_id: int, payload: GrilleSolveRequest) -> JSONResponse:
        return _handle_solve_defi(token=token, payload=payload, manche_id=manche_id)

    @app.post("/api/lutin/{token}/defi/abandon")
    def abandon_defi(token: str) -> JSONResponse:
        return _handle_abandon_defi(token=token, manche_id=1)

    @app.post("/api/lutin/{token}/defi/{manche_id}/abandon")
    def abandon_defi_manche(token: str, manche_id: int) -> JSONResponse:
        return _handle_abandon_defi(token=token, manche_id=manche_id)

    @app.get("/api/lutin/{token}/defi/indices")
    def get_defi_indices(token: str) -> JSONResponse:
        return _handle_get_indices(token=token, manche_id=1)

    @app.get("/api/lutin/{token}/defi/{manche_id}/indices")
    def get_defi_manche_indices(token: str, manche_id: int) -> JSONResponse:
        return _handle_get_indices(token=token, manche_id=manche_id)

    @app.get("/api/lutin/{token}/beneficiaire")
    def get_beneficiaire(token: str) -> JSONResponse:
        lutin_info = get_lutin_by_token(db_path, token)
        if not lutin_info:
            raise HTTPException(status_code=404, detail="Lien magique introuvable")

        year = lutin_info["year"]
        if not est_scellee(statut(db_path, year)):
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

    # Routes Espace Admin
    @app.get("/admin/login", response_class=HTMLResponse)
    def get_admin_login(request: Request) -> Any:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        now_ts = int(clock_fn().timestamp())
        if token and verify_session_token(token, session_secret, now_ts, max_age=SESSION_DURATION_SECONDS):
            return RedirectResponse(url="/admin", status_code=303)
        return templates.TemplateResponse(
            request=request,
            name="espace_admin_login.html",
            context={"error": None},
        )

    @app.post("/admin/login")
    def post_admin_login(request: Request) -> Any:
        forwarded_for = request.headers.get("x-forwarded-for")
        client_ip = (
            forwarded_for.split(",")[0].strip()
            if forwarded_for
            else (request.client.host if request.client else "127.0.0.1")
        )
        now_dt = clock_fn()
        now_ts = now_dt.timestamp()

        if rate_limiter.is_blocked(client_ip, now_ts):
            raise HTTPException(
                status_code=429,
                detail="Trop de tentatives de connexion. Veuillez réessayer plus tard.",
            )

        content_type = request.headers.get("content-type", "")
        body_bytes = anyio.from_thread.run(request.body)
        submitted_val = ""

        if "application/json" in content_type:
            try:
                data = json.loads(body_bytes.decode("utf-8"))
                if isinstance(data, dict):
                    submitted_val = str(data.get("password") or "")
            except Exception:
                submitted_val = ""
        else:
            try:
                parsed = urllib.parse.parse_qs(body_bytes.decode("utf-8"))
                submitted_val = parsed.get("password", [""])[0]
            except Exception:
                submitted_val = ""

        is_valid = bool(admin_pwd and hmac.compare_digest(submitted_val.encode("utf-8"), admin_pwd.encode("utf-8")))

        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        if is_valid:
            rate_limiter.record_success(client_ip)
            token = create_session_token(session_secret, int(now_ts))
            resp = RedirectResponse(url="/admin", status_code=303)
            resp.set_cookie(
                key=SESSION_COOKIE_NAME,
                value=token,
                max_age=SESSION_DURATION_SECONDS,
                httponly=True,
                samesite="strict",
                secure=is_https,
            )
            return resp
        else:
            rate_limiter.record_failure(client_ip, now_ts)
            return templates.TemplateResponse(
                request=request,
                name="espace_admin_login.html",
                context={"error": "Mot de passe administrateur incorrect."},
                status_code=401,
            )

    @app.api_route("/admin/logout", methods=["GET", "POST"])
    def logout_admin(request: Request) -> Any:
        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        resp = RedirectResponse(url="/admin/login", status_code=303)
        resp.delete_cookie(
            key=SESSION_COOKIE_NAME,
            httponly=True,
            samesite="strict",
            secure=is_https,
        )
        return resp

    @app.get("/admin", response_class=HTMLResponse)
    def get_espace_admin(request: Request, year: int | None = None) -> Any:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        now_ts = int(clock_fn().timestamp())
        if not token or not verify_session_token(token, session_secret, now_ts, max_age=SESSION_DURATION_SECONDS):
            return RedirectResponse(url="/admin/login", status_code=303)

        target_year = year if year is not None else annee_courante(db_path)
        summary = get_admin_edition_summary(db_path, target_year, res_dir=res_dir)
        available_years = summary.get("available_years", [target_year])
        base_url = str(request.base_url).rstrip("/")

        resp = templates.TemplateResponse(
            request=request,
            name="espace_admin.html",
            context={
                "request": request,
                "summary": summary,
                "selected_year": target_year,
                "available_years": available_years,
                "base_url": base_url,
            },
        )
        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        new_token = create_session_token(session_secret, now_ts)
        resp.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=new_token,
            max_age=SESSION_DURATION_SECONDS,
            httponly=True,
            samesite="strict",
            secure=is_https,
        )
        return resp

    return app
