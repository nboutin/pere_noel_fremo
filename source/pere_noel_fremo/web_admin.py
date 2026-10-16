"""Application FastAPI de l'Espace Admin, distincte de l'application publique (ADR-0009, ADR-0013)."""

import hashlib
import hmac
import json
import logging
import urllib.parse
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .admin import get_admin_edition_summary
from .config import (
    default_db_path,
    get_admin_password,
    get_admin_session_secret,
    get_base_url,
    resolve_res_dir,
)
from .database import init_db
from .edition import annee_courante
from .web_common import configure_web

SESSION_COOKIE_NAME = "admin_session"
SESSION_DURATION_SECONDS = 7200
SESSION_ABSOLUTE_LIFETIME_SECONDS = 43200
SESSION_CLOCK_SKEW_SECONDS = 300
MIN_SESSION_SECRET_BYTES = 32

logger = logging.getLogger(__name__)


def _session_signature(secret: str, password: str, issued_at: int, last_seen: int) -> str:
    password_digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.new(
        secret.encode("utf-8"),
        f"{issued_at}.{last_seen}.{password_digest}".encode(),
        hashlib.sha256,
    ).hexdigest()


def create_session_token(secret: str, password: str, issued_at: int, last_seen: int) -> str:
    """Jeton ``issued_at.last_seen.signature`` lié au mot de passe admin (son changement le révoque)."""
    return f"{issued_at}.{last_seen}.{_session_signature(secret, password, issued_at, last_seen)}"


def verify_session_token(token: str, secret: str, password: str, now: int) -> bool:
    parts = token.split(".") if token else []
    if len(parts) != 3:
        return False
    try:
        issued_at, last_seen = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    if not hmac.compare_digest(parts[2], _session_signature(secret, password, issued_at, last_seen)):
        return False
    return not (
        now - last_seen > SESSION_DURATION_SECONDS
        or now - issued_at > SESSION_ABSOLUTE_LIFETIME_SECONDS
        or issued_at > now + SESSION_CLOCK_SKEW_SECONDS
        or last_seen > now + SESSION_CLOCK_SKEW_SECONDS
    )


class LoginRateLimiter:
    """Limiteur de tentatives de connexion, clé = IP du client TCP (``request.client.host``).

    En pratique le limiteur est global : derrière ``tailscale serve``, la liaison loopback et
    le NAT Docker, tous les clients apparaissent sous l'IP de la passerelle Docker, donc
    ``max_attempts`` échecs bloquent la connexion pour tout le monde pendant ``window_seconds``
    (ADR-0013 §4, amendement du 16 octobre 2026). C'est accepté : le tailnet ne contient que les
    appareils de l'organisateur. ``X-Forwarded-For`` et ``Tailscale-User-Login`` ne sont jamais lus.
    """

    def __init__(self, max_attempts: int = 5, window_seconds: int = 900) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = {}

    def is_blocked(self, ip: str, now: float) -> bool:
        self._cleanup(now)
        return len(self._attempts.get(ip, [])) >= self.max_attempts

    def record_failure(self, ip: str, now: float) -> None:
        self._cleanup(now)
        self._attempts.setdefault(ip, []).append(now)

    def record_success(self, ip: str) -> None:
        self._attempts.pop(ip, None)

    def reset(self) -> None:
        self._attempts.clear()

    def _cleanup(self, now: float) -> None:
        """Purge les tentatives expirées de toutes les IP."""
        for key in list(self._attempts):
            recent = [t for t in self._attempts[key] if now - t < self.window_seconds]
            if recent:
                self._attempts[key] = recent
            else:
                del self._attempts[key]


def create_admin_app(
    db_path: Path | str | None = None,
    res_dir: Path | str | None = None,
    clock: Callable[[], datetime] | None = None,
    admin_password: str | None = None,
    admin_session_secret: str | None = None,
) -> FastAPI:
    """Crée l'application FastAPI de l'Espace Admin (listener dédié, réservé au tailnet)."""
    resolved_res_dir = Path(res_dir) if res_dir is not None else resolve_res_dir()
    resolved_db_path = Path(db_path) if db_path is not None else default_db_path(resolved_res_dir)
    init_db(resolved_db_path)
    db_path = resolved_db_path
    res_dir = resolved_res_dir
    clock_fn: Callable[[], datetime] = clock if clock is not None else (lambda: datetime.now(timezone.utc))

    admin_pwd = admin_password if admin_password is not None else get_admin_password(res_dir)
    session_sec = admin_session_secret if admin_session_secret is not None else get_admin_session_secret(res_dir)
    configured_base_url = get_base_url(res_dir)
    session_password = admin_pwd or ""
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

    app = FastAPI(title="Père Noël de la Frémo - Espace Admin")
    templates = configure_web(app)

    @app.middleware("http")
    async def admin_guard(request: Request, call_next: Callable[[Request], Any]) -> Any:
        # Garde-fou unique : une requête arrivée par Tailscale Funnel n'atteint jamais l'Espace Admin.
        path = request.url.path.lower()
        is_admin_path = path == "/admin" or path.startswith("/admin/")
        if request.headers.get("tailscale-funnel-request") == "?1" or (is_admin_path and not admin_enabled):
            return templates.TemplateResponse(
                request=request,
                name="erreur_404.html",
                status_code=404,
            )
        return await call_next(request)

    def _set_session_cookie(resp: Any, token: str) -> None:
        resp.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=SESSION_DURATION_SECONDS,
            httponly=True,
            samesite="strict",
            secure=True,
        )

    @app.get("/admin/login", response_class=HTMLResponse)
    def get_admin_login(request: Request) -> Any:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        now_ts = int(clock_fn().timestamp())
        if token and verify_session_token(token, session_secret, session_password, now_ts):
            return RedirectResponse(url="/admin", status_code=303)
        return templates.TemplateResponse(
            request=request,
            name="espace_admin_login.html",
            context={"error": None},
        )

    @app.post("/admin/login")
    async def post_admin_login(request: Request) -> Any:
        client_ip = request.client.host if request.client else "127.0.0.1"
        now_ts = clock_fn().timestamp()

        if rate_limiter.is_blocked(client_ip, now_ts):
            return templates.TemplateResponse(
                request=request,
                name="espace_admin_login.html",
                context={"error": "Trop de tentatives de connexion. Veuillez réessayer plus tard."},
                status_code=429,
            )

        content_type = request.headers.get("content-type", "")
        body_bytes = await request.body()
        submitted_val = ""

        try:
            text = body_bytes.decode("utf-8")
            if "application/json" in content_type:
                data = json.loads(text)
                if isinstance(data, dict):
                    submitted_val = str(data.get("password") or "")
            else:
                submitted_val = urllib.parse.parse_qs(text).get("password", [""])[0]
        except (UnicodeDecodeError, json.JSONDecodeError):
            submitted_val = ""

        is_valid = bool(admin_pwd and hmac.compare_digest(submitted_val.encode("utf-8"), admin_pwd.encode("utf-8")))

        if is_valid:
            rate_limiter.record_success(client_ip)
            resp = RedirectResponse(url="/admin", status_code=303)
            _set_session_cookie(resp, create_session_token(session_secret, session_password, int(now_ts), int(now_ts)))
            return resp
        rate_limiter.record_failure(client_ip, now_ts)
        return templates.TemplateResponse(
            request=request,
            name="espace_admin_login.html",
            context={"error": "Mot de passe administrateur incorrect."},
            status_code=401,
        )

    @app.api_route("/admin/logout", methods=["GET", "POST"])
    def logout_admin() -> Any:
        resp = RedirectResponse(url="/admin/login", status_code=303)
        resp.delete_cookie(
            key=SESSION_COOKIE_NAME,
            httponly=True,
            samesite="strict",
            secure=True,
        )
        return resp

    @app.get("/admin", response_class=HTMLResponse)
    def get_espace_admin(request: Request, year: int | None = None) -> Any:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        now_ts = int(clock_fn().timestamp())
        if not token or not verify_session_token(token, session_secret, session_password, now_ts):
            return RedirectResponse(url="/admin/login", status_code=303)

        target_year = year if year is not None else annee_courante(db_path)
        summary = get_admin_edition_summary(db_path, target_year)
        available_years = summary.get("available_years", [target_year])
        base_url = (configured_base_url or str(request.base_url)).strip().rstrip("/")

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
        issued_at = int(token.split(".")[0])
        _set_session_cookie(resp, create_session_token(session_secret, session_password, issued_at, now_ts))
        return resp

    return app
