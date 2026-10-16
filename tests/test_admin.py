"""Tests pour l'Espace Admin : défense en profondeur, garde Tailscale Funnel et authentification."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pere_noel_fremo.database import init_db
from pere_noel_fremo.tokens import create_or_get_token
from pere_noel_fremo.web import (
    SESSION_COOKIE_NAME,
    LoginRateLimiter,
    create_app,
    create_session_token,
    is_tailscale_funnel_request,
    verify_session_token,
)
from starlette.requests import Request
from starlette.testclient import TestClient


@pytest.fixture
def admin_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "fremo_admin_test.db"
    init_db(db_file)
    from pere_noel_fremo.database import get_db_connection

    conn = get_db_connection(db_file)
    with conn:
        conn.execute(
            "INSERT INTO lutins (id, fullname, email) VALUES ('fbonnet', 'François Bonnet', 'fb@example.com');"
        )
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'announced');")
    conn.close()
    return db_file


@pytest.fixture
def mutable_clock() -> list[datetime]:
    # Horloge mutable pour tester l'expiration de session
    now = datetime(2026, 12, 1, 10, 0, 0, tzinfo=timezone.utc)
    return [now]


@pytest.fixture
def admin_client(admin_db: Path, mutable_clock: list[datetime]) -> TestClient:
    app = create_app(
        db_path=admin_db,
        clock=lambda: mutable_clock[0],
        admin_password="secret_admin_test_password",
        admin_session_secret="test_session_secret_at_least_32_bytes_long",
    )
    # base_url https pour que httpx/TestClient conserve les cookies secure=True
    return TestClient(app, base_url="https://testserver")


# ==============================================================================
# 1. Unitaire : Helpers de jeton, garde Funnel et Limiteur
# ==============================================================================


def test_session_token_lifecycle_and_tampering() -> None:
    secret = "my_super_secret"
    now_ts = 1000000

    token = create_session_token(secret, now_ts)
    assert token.startswith(f"{now_ts}.")
    assert verify_session_token(token, secret, now=now_ts) is True

    # 1. Signature corrompue
    tampered = f"{token[:-4]}abcd"
    assert verify_session_token(tampered, secret, now=now_ts) is False

    # 2. Secret différent
    assert verify_session_token(token, "wrong_secret", now=now_ts) is False

    # 3. Format invalide
    assert verify_session_token("", secret, now=now_ts) is False
    assert verify_session_token("invalid_no_dot", secret, now=now_ts) is False
    assert verify_session_token("notanumber.signature", secret, now=now_ts) is False
    assert verify_session_token("1.2.3", secret, now=now_ts) is False

    # 4. Expiration (> 7200 secondes)
    assert verify_session_token(token, secret, now=now_ts + 7200) is True
    assert verify_session_token(token, secret, now=now_ts + 7201) is False

    # 5. Timestamp trop lointain dans le futur (> 300 secondes d'écart)
    future_token = create_session_token(secret, now_ts + 350)
    assert verify_session_token(future_token, secret, now=now_ts) is False


def test_is_tailscale_funnel_request() -> None:
    # 1. En-tête Tailscale-Funnel-Request
    req1 = Request({"type": "http", "headers": [(b"tailscale-funnel-request", b"?1")]})
    assert is_tailscale_funnel_request(req1) is True

    # 2. Port 10000 dans Host
    req2 = Request({"type": "http", "headers": [(b"host", b"homelab.tail7d8b91.ts.net:10000")]})
    assert is_tailscale_funnel_request(req2) is True

    # 3. Port 10000 dans X-Forwarded-Host
    req3 = Request({"type": "http", "headers": [(b"x-forwarded-host", b"site.example.com:10000")]})
    assert is_tailscale_funnel_request(req3) is True

    # 4. Requête normale sans Funnel
    req4 = Request(
        {
            "type": "http",
            "headers": [
                (b"host", b"192.168.2.20:8000"),
                (b"user-agent", b"pytest"),
            ],
        }
    )
    assert is_tailscale_funnel_request(req4) is False


def test_login_rate_limiter_logic() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60)
    ip = "192.168.1.10"
    t0 = 1000.0

    assert limiter.is_blocked(ip, t0) is False

    limiter.record_failure(ip, t0)
    assert limiter.is_blocked(ip, t0) is False
    limiter.record_failure(ip, t0 + 1)
    assert limiter.is_blocked(ip, t0 + 1) is False
    limiter.record_failure(ip, t0 + 2)
    # Après 3 échecs, bloqué
    assert limiter.is_blocked(ip, t0 + 2) is True

    # Une autre IP n'est pas bloquée
    assert limiter.is_blocked("192.168.1.20", t0 + 2) is False

    # Après expiration de la fenêtre (61 secondes), n'est plus bloqué
    assert limiter.is_blocked(ip, t0 + 65) is False

    # Succès réinitialise
    limiter.record_failure(ip, t0 + 70)
    limiter.record_success(ip)
    assert limiter.is_blocked(ip, t0 + 70) is False


# ==============================================================================
# 2. Garde Tailscale Funnel : Rejet furtif 404
# ==============================================================================


@pytest.mark.parametrize(
    "headers",
    [
        {"tailscale-funnel-request": "?1"},
        {"Tailscale-Funnel-Request": "?1"},
        {"host": "homelab.tail7d8b91.ts.net:10000"},
        {"x-forwarded-host": "homelab.tail7d8b91.ts.net:10000"},
    ],
)
def test_funnel_request_blocked_on_admin_routes(admin_client: TestClient, headers: dict[str, str]) -> None:
    # 1. /admin
    resp = admin_client.get("/admin", headers=headers, follow_redirects=False)
    assert resp.status_code == 404
    assert "404" in resp.text
    assert "Lien magique introuvable" in resp.text

    # 2. /admin/login (GET)
    resp_login = admin_client.get("/admin/login", headers=headers, follow_redirects=False)
    assert resp_login.status_code == 404

    # 3. /admin/login (POST)
    resp_login_post = admin_client.post(
        "/admin/login",
        data={"password": "secret_admin_test_password"},
        headers=headers,
        follow_redirects=False,
    )
    assert resp_login_post.status_code == 404

    # 4. /admin/logout
    resp_logout = admin_client.get("/admin/logout", headers=headers, follow_redirects=False)
    assert resp_logout.status_code == 404


def test_funnel_request_allows_public_routes(admin_client: TestClient, admin_db: Path) -> None:
    token = create_or_get_token(admin_db, "fbonnet", 2026)

    # /scores est public, ne doit pas renvoyer 404
    resp_scores = admin_client.get(
        "/scores",
        headers={"tailscale-funnel-request": "?1", "host": "homelab.tail7d8b91.ts.net:10000"},
    )
    assert resp_scores.status_code == 200

    # /lutin/{token} est public
    resp_lutin = admin_client.get(
        f"/lutin/{token}",
        headers={"tailscale-funnel-request": "?1", "host": "homelab.tail7d8b91.ts.net:10000"},
    )
    assert resp_lutin.status_code == 200


# ==============================================================================
# 3. Accès non authentifié à /admin -> Redirection vers /admin/login
# ==============================================================================


def test_admin_requires_authentication(admin_client: TestClient) -> None:
    # Sans cookie
    resp = admin_client.get("/admin", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"

    # Avec cookie invalide
    admin_client.cookies.set(SESSION_COOKIE_NAME, "bad_token")
    resp_bad = admin_client.get("/admin", follow_redirects=False)
    assert resp_bad.status_code == 303
    assert resp_bad.headers["location"] == "/admin/login"


def test_admin_login_page_renders_form(admin_client: TestClient) -> None:
    resp = admin_client.get("/admin/login")
    assert resp.status_code == 200
    assert "Espace Admin" in resp.text
    assert '<form method="post" action="/admin/login">' in resp.text
    assert 'type="password"' in resp.text


# ==============================================================================
# 4. Authentification : échecs, anti-brute force et succès
# ==============================================================================


def test_login_failed_with_invalid_password(admin_client: TestClient) -> None:
    resp = admin_client.post(
        "/admin/login",
        data={"password": "mauvais_mot_de_passe"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    assert "Mot de passe administrateur incorrect" in resp.text
    assert SESSION_COOKIE_NAME not in resp.cookies


def test_anti_brute_force_rate_limits_after_5_failures(admin_client: TestClient) -> None:
    # 5 échecs consécutifs
    for i in range(5):
        resp = admin_client.post(
            "/admin/login",
            data={"password": f"wrong_{i}"},
            follow_redirects=False,
        )
        assert resp.status_code == 401

    # 6ème tentative (même avec bon mot de passe) bloquée avec 429
    resp_blocked = admin_client.post(
        "/admin/login",
        data={"password": "secret_admin_test_password"},
        follow_redirects=False,
    )
    assert resp_blocked.status_code == 429
    assert "Trop de tentatives" in resp_blocked.text


def test_login_success_sets_session_cookie_and_redirects(admin_client: TestClient) -> None:
    resp = admin_client.post(
        "/admin/login",
        data={"password": "secret_admin_test_password"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"

    # Vérification des attributs du cookie
    set_cookie_header = resp.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie_header
    assert "HttpOnly" in set_cookie_header or "httponly" in set_cookie_header.lower()
    assert "SameSite=strict" in set_cookie_header or "samesite=strict" in set_cookie_header.lower()
    assert "Secure" in set_cookie_header or "secure" in set_cookie_header.lower()
    assert "Max-Age=7200" in set_cookie_header or "max-age=7200" in set_cookie_header.lower()


def test_login_with_json_payload(admin_client: TestClient) -> None:
    # Support des requêtes JSON
    resp = admin_client.post(
        "/admin/login",
        json={"password": "secret_admin_test_password"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"


def test_login_when_no_admin_password_configured(admin_db: Path) -> None:
    # App créée sans mot de passe configuré
    app_no_pass = create_app(
        db_path=admin_db,
        admin_password="",
        admin_session_secret="secret_key_12345678901234567890",
    )
    client_no_pass = TestClient(app_no_pass, base_url="https://testserver")

    resp = client_no_pass.post(
        "/admin/login",
        data={"password": "any_password"},
        follow_redirects=False,
    )
    assert resp.status_code == 401


# ==============================================================================
# 5. Session active, expiration et déconnexion
# ==============================================================================


def test_valid_session_accesses_admin_and_logout(admin_client: TestClient, mutable_clock: list[datetime]) -> None:
    # 1. Connexion réussie
    login_resp = admin_client.post(
        "/admin/login",
        data={"password": "secret_admin_test_password"},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200
    assert "Espace Admin" in login_resp.text
    assert "Se déconnecter" in login_resp.text

    # 2. Accès direct à /admin avec le cookie conservé
    admin_resp = admin_client.get("/admin", follow_redirects=False)
    assert admin_resp.status_code == 200
    assert "Espace Admin" in admin_resp.text
    assert "Bienvenue dans l'Espace Admin" in admin_resp.text

    # 3. Visiter /admin/login alors qu'on est déjà connecté redirige vers /admin
    login_get = admin_client.get("/admin/login", follow_redirects=False)
    assert login_get.status_code == 303
    assert login_get.headers["location"] == "/admin"

    # 4. Déconnexion via POST /admin/logout
    logout_resp = admin_client.post("/admin/logout", follow_redirects=False)
    assert logout_resp.status_code == 303
    assert logout_resp.headers["location"] == "/admin/login"

    # 5. Après déconnexion, l'accès à /admin renvoie vers /admin/login
    admin_after_logout = admin_client.get("/admin", follow_redirects=False)
    assert admin_after_logout.status_code == 303
    assert admin_after_logout.headers["location"] == "/admin/login"


def test_session_expiration_after_2_hours(admin_client: TestClient, mutable_clock: list[datetime]) -> None:
    # 1. Connexion réussie à T0
    admin_client.post(
        "/admin/login",
        data={"password": "secret_admin_test_password"},
        follow_redirects=False,
    )

    # 2. Accès à T0 + 1h59min (valide)
    mutable_clock[0] += timedelta(seconds=7190)
    resp_still_valid = admin_client.get("/admin", follow_redirects=False)
    assert resp_still_valid.status_code == 200

    # 3. Accès à T0 + 2h01min (expiré : > 7200s)
    mutable_clock[0] += timedelta(seconds=20)
    resp_expired = admin_client.get("/admin", follow_redirects=False)
    assert resp_expired.status_code == 303
    assert resp_expired.headers["location"] == "/admin/login"


def test_logout_via_get_method(admin_client: TestClient) -> None:
    admin_client.post(
        "/admin/login",
        data={"password": "secret_admin_test_password"},
        follow_redirects=False,
    )
    resp = admin_client.get("/admin/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"
