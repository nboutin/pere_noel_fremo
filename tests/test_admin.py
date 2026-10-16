"""Tests pour l'Espace Admin : défense en profondeur, garde Tailscale Funnel et authentification."""

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pere_noel_fremo.database import init_db
from pere_noel_fremo.tokens import create_or_get_token
from pere_noel_fremo.web import create_app
from pere_noel_fremo.web_admin import (
    SESSION_COOKIE_NAME,
    LoginRateLimiter,
    create_admin_app,
    create_session_token,
    verify_session_token,
)
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
    app = create_admin_app(
        db_path=admin_db,
        clock=lambda: mutable_clock[0],
        admin_password="secret_admin_test_password",
        admin_session_secret="test_session_secret_at_least_32_bytes_long",
    )
    # base_url https pour que httpx/TestClient conserve les cookies secure=True
    return TestClient(app, base_url="https://testserver")


# ==============================================================================
# 1. Unitaire : Helpers de token de session, garde Funnel et Limiteur
# ==============================================================================


def test_session_token_lifecycle_and_tampering() -> None:
    secret = "my_super_secret"
    pwd = "pwd_a"
    now_ts = 1000000

    token = create_session_token(secret, pwd, issued_at=now_ts, last_seen=now_ts)
    assert token.startswith(f"{now_ts}.{now_ts}.")
    assert verify_session_token(token, secret, pwd, now=now_ts) is True

    # 1. Signature corrompue
    tampered = f"{token[:-4]}abcd"
    assert verify_session_token(tampered, secret, pwd, now=now_ts) is False

    # 2. Secret différent, mot de passe différent
    assert verify_session_token(token, "wrong_secret", pwd, now=now_ts) is False
    assert verify_session_token(token, secret, "pwd_b", now=now_ts) is False

    # 3. Format invalide, dont l'ancien format à deux parties
    assert verify_session_token("", secret, pwd, now=now_ts) is False
    assert verify_session_token("invalid_no_dot", secret, pwd, now=now_ts) is False
    assert verify_session_token("a.b.signature", secret, pwd, now=now_ts) is False
    assert verify_session_token("1.2.3.4", secret, pwd, now=now_ts) is False
    old_sig = hmac.new(secret.encode(), str(now_ts).encode(), hashlib.sha256).hexdigest()
    assert verify_session_token(f"{now_ts}.{old_sig}", secret, pwd, now=now_ts) is False

    # 4. Inactivité (> 7200 secondes)
    assert verify_session_token(token, secret, pwd, now=now_ts + 7200) is True
    assert verify_session_token(token, secret, pwd, now=now_ts + 7201) is False

    # 5. Durée absolue (> 43200 secondes) malgré une activité récente
    old = create_session_token(secret, pwd, issued_at=now_ts, last_seen=now_ts + 43000)
    assert verify_session_token(old, secret, pwd, now=now_ts + 43200) is True
    assert verify_session_token(old, secret, pwd, now=now_ts + 43201) is False

    # 6. Horodatage trop lointain dans le futur (> 300 secondes d'écart)
    future_token = create_session_token(secret, pwd, issued_at=now_ts + 350, last_seen=now_ts + 350)
    assert verify_session_token(future_token, secret, pwd, now=now_ts) is False
    assert verify_session_token(future_token, secret, pwd, now=now_ts + 100) is True


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
# 2. Garde-fou Funnel : rejet furtif 404
# ==============================================================================


@pytest.mark.parametrize(
    "headers",
    [
        {"tailscale-funnel-request": "?1"},
        {"Tailscale-Funnel-Request": "?1"},
        {"tailscale-funnel-request": "?1", "host": "homelab.tail7d8b91.ts.net:8444"},
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


def test_funnel_guard_covers_every_path(admin_client: TestClient) -> None:
    resp = admin_client.get("/static/inexistant.css", headers={"Tailscale-Funnel-Request": "?1"})
    assert resp.status_code == 404
    assert "Lien magique introuvable" in resp.text


@pytest.mark.parametrize(
    "headers",
    [
        {"host": "homelab.tail7d8b91.ts.net:10000"},
        {"x-forwarded-host": "homelab.tail7d8b91.ts.net:10000"},
        {"Tailscale-Funnel-Request": "?0"},
    ],
)
def test_port_10000_without_funnel_header_is_served_normally(admin_client: TestClient, headers: dict[str, str]) -> None:
    # Le tailnet atteint l'Espace Admin avec n'importe quel Host : seul l'en-tête Funnel compte.
    resp = admin_client.get("/admin/login", headers=headers, follow_redirects=False)
    assert resp.status_code == 200
    assert admin_client.get("/admin", headers=headers, follow_redirects=False).status_code == 303


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_all_admin_cookies_are_secure_whatever_the_scheme(admin_db: Path, scheme: str) -> None:
    app = create_admin_app(
        db_path=admin_db,
        admin_password="secret_admin_test_password",
        admin_session_secret="test_session_secret_at_least_32_bytes_long",
    )
    client = TestClient(app, base_url=f"{scheme}://testserver")
    login = client.post("/admin/login", data={"password": "secret_admin_test_password"}, follow_redirects=False)
    set_cookie = login.headers["set-cookie"]
    assert "secure" in set_cookie.lower()

    # Cookie réinjecté à la main : le client httpx ne renvoie pas un cookie Secure en http://
    cookie = set_cookie.split(";")[0].split("=", 1)[1]
    client.cookies.clear()
    dash = client.get("/admin", headers={"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"})
    assert dash.status_code == 200
    assert "secure" in dash.headers["set-cookie"].lower()

    logout = client.get("/admin/logout", follow_redirects=False)
    assert "secure" in logout.headers["set-cookie"].lower()


def test_public_app_has_no_admin_routes(admin_db: Path) -> None:
    app = create_app(db_path=admin_db)
    assert not [r for r in app.routes if getattr(r, "path", "").startswith("/admin")]
    client = TestClient(app, base_url="https://testserver")
    assert client.get("/admin", follow_redirects=False).status_code == 404
    assert client.get("/admin/login", follow_redirects=False).status_code == 404
    assert client.post("/admin/login", data={"password": "x"}, follow_redirects=False).status_code == 404
    assert client.get("/admin/logout", follow_redirects=False).status_code == 404
    assert client.post("/admin/logout", follow_redirects=False).status_code == 404


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


def test_anti_brute_force_ignores_x_forwarded_for(admin_client: TestClient) -> None:
    for i in range(5):
        resp = admin_client.post(
            "/admin/login",
            data={"password": f"wrong_{i}"},
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
            follow_redirects=False,
        )
        assert resp.status_code == 401
    resp_blocked = admin_client.post(
        "/admin/login",
        data={"password": "wrong_6"},
        headers={"X-Forwarded-For": "10.0.0.6"},
        follow_redirects=False,
    )
    assert resp_blocked.status_code == 429


def test_rate_limit_response_is_html(admin_client: TestClient) -> None:
    for i in range(5):
        admin_client.post("/admin/login", data={"password": f"wrong_{i}"}, follow_redirects=False)
    resp = admin_client.post("/admin/login", data={"password": "x"}, follow_redirects=False)
    assert resp.status_code == 429
    assert resp.headers["content-type"].startswith("text/html")
    assert "Trop de tentatives" in resp.text


def test_rate_limiter_purges_all_expired_entries() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60)
    limiter.record_failure("10.0.0.1", 1000.0)
    limiter.record_failure("10.0.0.2", 1001.0)
    limiter.is_blocked("10.0.0.3", 1100.0)
    assert limiter._attempts == {}


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"{not json", "application/json"),
        (b"\xff\xfe\x00", "application/json"),
        (b"password=\xff\xfe", "application/x-www-form-urlencoded"),
    ],
)
def test_login_with_malformed_body_returns_401(admin_client: TestClient, content: bytes, content_type: str) -> None:
    resp = admin_client.post(
        "/admin/login",
        content=content,
        headers={"Content-Type": content_type},
        follow_redirects=False,
    )
    assert resp.status_code == 401


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
    app_no_pass = create_admin_app(
        db_path=admin_db,
        admin_password="",
        admin_session_secret="secret_key_1234567890123456789012345",
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


def test_session_expiration_after_2_hours_inactivity(admin_client: TestClient, mutable_clock: list[datetime]) -> None:
    # 1. Connexion réussie à T0
    admin_client.post(
        "/admin/login",
        data={"password": "secret_admin_test_password"},
        follow_redirects=False,
    )

    # 2. Inactivité de plus de 2 heures (> 7200s) sans aucune requête
    mutable_clock[0] += timedelta(seconds=7201)
    resp_expired = admin_client.get("/admin", follow_redirects=False)
    assert resp_expired.status_code == 303
    assert resp_expired.headers["location"] == "/admin/login"


def test_sliding_session_refreshes_cookie_and_extends_lifetime(
    admin_client: TestClient, mutable_clock: list[datetime]
) -> None:
    # 1. Connexion réussie à T0
    login_resp = admin_client.post(
        "/admin/login",
        data={"password": "secret_admin_test_password"},
        follow_redirects=False,
    )
    assert login_resp.status_code == 303
    initial_cookie = admin_client.cookies.get(SESSION_COOKIE_NAME)
    assert initial_cookie is not None

    # 2. Accès à T0 + 1h (3600s) -> la session est rafraîchie avec un nouveau cookie
    mutable_clock[0] += timedelta(seconds=3600)
    resp1 = admin_client.get("/admin", follow_redirects=False)
    assert resp1.status_code == 200
    refreshed_cookie = admin_client.cookies.get(SESSION_COOKIE_NAME)
    assert refreshed_cookie != initial_cookie
    assert SESSION_COOKIE_NAME in resp1.headers.get("set-cookie", "")

    # 3. Accès à T0 + 2h30 (5400s après resp1, 9000s au total après login)
    # Sans glissement de session (expiration à 2h depuis le login), cela aurait expiré.
    # Grâce au glissement (moins de 2h d'inactivité depuis le dernier accès), l'accès réussit !
    mutable_clock[0] += timedelta(seconds=5400)
    resp2 = admin_client.get("/admin", follow_redirects=False)
    assert resp2.status_code == 200

    # 4. Inactivité de plus de 2h après le dernier accès (7201s) -> session expirée
    mutable_clock[0] += timedelta(seconds=7201)
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


# ==============================================================================
# 6. Espace Admin : Interface web, Bandeau de synthèse, Filtres et Admin aveugle
# ==============================================================================


@pytest.fixture
def rich_admin_db(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    db_file = tmp_path / "fremo_rich_admin.db"
    init_db(db_file)
    from pere_noel_fremo.database import get_db_connection
    from pere_noel_fremo.tokens import mark_token_sent

    conn = get_db_connection(db_file)
    tokens: dict[str, str] = {}
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2025, 'revealed');")
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'announced');")

        # Lutins (4 actifs, 1 inactif)
        conn.execute(
            "INSERT INTO lutins (id, fullname, email, is_active) VALUES ('alice', 'Alice Martin', 'alice@test.fr', 1);"
        )
        conn.execute(
            "INSERT INTO lutins (id, fullname, email, is_active) VALUES ('bob', 'Bob Dupont', 'bob@test.fr', 1);"
        )
        conn.execute(
            "INSERT INTO lutins (id, fullname, email, is_active) "
            "VALUES ('charlie', 'Charlie Durand', 'charlie@test.fr', 1);"
        )
        conn.execute(
            "INSERT INTO lutins (id, fullname, email, is_active) VALUES ('denis', 'Denis Inactif', 'denis@test.fr', 0);"
        )
        conn.execute(
            "INSERT INTO lutins (id, fullname, email, is_active) VALUES ('eve', 'Eve Lambert', 'eve@test.fr', 1);"
        )

        # 2026 Presences: Alice=confirme, Bob=absent, Charlie=en attente (aucun enregistrement), Eve=confirme
        conn.execute(
            "INSERT INTO presences (lutin_id, year, present, updated_at) "
            "VALUES ('alice', 2026, 1, '2026-11-01 10:00:00');"
        )
        conn.execute(
            "INSERT INTO presences (lutin_id, year, present, updated_at) "
            "VALUES ('bob', 2026, 0, '2026-11-02 11:00:00');"
        )
        conn.execute(
            "INSERT INTO presences (lutin_id, year, present, updated_at) "
            "VALUES ('eve', 2026, 1, '2026-11-03 12:00:00');"
        )

        # 2025 Presences: Alice=absent
        conn.execute(
            "INSERT INTO presences (lutin_id, year, present, updated_at) "
            "VALUES ('alice', 2025, 0, '2025-11-01 10:00:00');"
        )

        # 2026 Scores Défi:
        # Alice: résolu manche 1, 42.5s, 2 tentatives
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('alice', 2026, 1, 'LutinAgile', '2026-12-01 10:00:00', 1, 42.5, '2026-12-01 10:00:42', 2);
        """)
        # Bob: en cours (commencé mais non terminé)
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('bob', 2026, 1, 'LutinRapide', '2026-12-01 10:00:00', 0, NULL, NULL, 1);
        """)
        # Eve: abandonné (terminé sans résoudre)
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('eve', 2026, 1, 'LutinMalicieux', '2026-12-01 10:00:00', 0, NULL, '2026-12-01 10:10:00', 3);
        """)

        # Attributions secrètes en 2026 (Alice offre à Bob)
        conn.execute("INSERT INTO attributions (year, donneur_id, beneficiaire_id) VALUES (2026, 'alice', 'bob');")

    conn.close()

    tok_alice = create_or_get_token(db_file, "alice", 2026)
    mark_token_sent(db_file, tok_alice)
    tok_bob = create_or_get_token(db_file, "bob", 2026)
    tokens["alice"] = tok_alice
    tokens["bob"] = tok_bob

    return db_file, tokens


@pytest.fixture
def rich_admin_client(
    rich_admin_db: tuple[Path, dict[str, str]], mutable_clock: list[datetime]
) -> tuple[TestClient, dict[str, str]]:
    db_file, tokens = rich_admin_db
    app = create_admin_app(
        db_path=db_file,
        clock=lambda: mutable_clock[0],
        admin_password="secret_admin_test_password",
        admin_session_secret="test_session_secret_at_least_32_bytes_long",
    )
    return TestClient(app, base_url="https://testserver"), tokens


def test_admin_dashboard_rendering_and_metrics(
    rich_admin_client: tuple[TestClient, dict[str, str]],
) -> None:
    client, tokens = rich_admin_client

    # Connexion préalable
    login_resp = client.post(
        "/admin/login",
        data={"password": "secret_admin_test_password"},
        follow_redirects=False,
    )
    assert login_resp.status_code == 303

    # Consultation de /admin (année par défaut: 2026)
    resp = client.get("/admin")
    assert resp.status_code == 200
    html = resp.text

    # 1. En-tête et navigation
    assert "🎅 Espace Admin 🎄" in html
    assert "Suivi confidentiel de l'Édition" in html
    assert "Se déconnecter" in html
    assert '<select id="select-year"' in html
    assert '<option value="2026" selected>2026</option>' in html
    assert '<option value="2025" >2025</option>' in html

    # 2. Cartes de synthèse (métriques)
    assert "Inscrits" in html
    assert "Confirmés" in html
    assert "Absents" in html
    assert "En attente" in html
    assert "Liens magiques envoyés" in html
    assert "Résolution du Défi" in html

    # Valeurs attendues pour 2026 (4 lutins actifs)
    assert ">4</div>" in html  # Total actifs
    assert ">2</div>" in html  # Confirmés (Alice, Eve)
    assert ">1</div>" in html  # Absents (Bob) et En attente (Charlie)
    assert "25.0%" in html  # Taux résolution défi (1 / 4)

    # 3. Barre de filtres
    assert "Tous (5)" in html
    assert "Confirmés (2)" in html
    assert "Absents (1)" in html
    assert "En attente (1)" in html
    assert "Inactifs (1)" in html
    assert "filterLutins('all')" in html
    assert "filterLutins('confirme')" in html
    assert "filterLutins('absent')" in html
    assert "filterLutins('en_attente')" in html
    assert "filterLutins('inactif')" in html

    # En-têtes du tableau respectant GLOSSARY.md (pas de "Compte")
    assert "<th>Statut</th>" in html
    assert "<th>Compte</th>" not in html
    assert "comptes" not in html

    # 4. Badges présence
    assert "✅ Confirmé" in html
    assert "❌ Absent" in html
    assert "⏳ En attente" in html

    # 5. Badges Défi
    assert "🏆 Résolu" in html
    assert "42.5s" in html
    assert "(2 tent.)" in html
    assert "⏳ En cours" in html
    assert "🚫 Abandonné" in html
    assert "⚪ Non commencé" in html

    # 6. Statut Actif / Inactif des Lutins
    assert "Denis Inactif" in html
    assert "Inactif" in html

    # 7. Lien magique & Bouton Copier l'URL
    assert "✉️ Envoyé" in html
    assert "Non envoyé" in html
    assert "Copier l'URL" in html
    assert f"https://testserver/lutin/{tokens['alice']}" in html


def test_admin_dashboard_year_switching(
    rich_admin_client: tuple[TestClient, dict[str, str]],
) -> None:
    client, _ = rich_admin_client
    client.post(
        "/admin/login",
        data={"password": "secret_admin_test_password"},
        follow_redirects=False,
    )

    resp_2025 = client.get("/admin?year=2025")
    assert resp_2025.status_code == 200
    html = resp_2025.text

    assert '<option value="2025" selected>2025</option>' in html
    assert "Édition 2025" in html
    assert "revealed" in html


def test_blind_admin_strict_guarantee(
    rich_admin_client: tuple[TestClient, dict[str, str]],
) -> None:
    client, _ = rich_admin_client
    client.post(
        "/admin/login",
        data={"password": "secret_admin_test_password"},
        follow_redirects=False,
    )

    resp = client.get("/admin")
    assert resp.status_code == 200
    html = resp.text.lower()

    # Garantie absolue d'Admin aveugle (ADR-0005, ADR-0013) :
    # Aucun terme ni association de table attributions ne doit être présent
    assert "attributions" not in html
    assert "donneur" not in html
    assert "beneficiaire" not in html

    # Vérification que le couple secret 'Alice -> Bob' n'est aucunement exposé
    assert "alice martin -> bob dupont" not in html
    assert "bob dupont (bénéficiaire)" not in html


def test_public_pages_do_not_leak_admin(
    rich_admin_db: tuple[Path, dict[str, str]],
) -> None:
    db_file, tokens = rich_admin_db
    client = TestClient(create_app(db_path=db_file), base_url="https://testserver")

    # 1. Page publique de classement des scores (/scores)
    resp_scores = client.get("/scores")
    assert resp_scores.status_code == 200
    assert "/admin" not in resp_scores.text

    # 2. Page publique de l'Espace Lutin (/lutin/{token})
    resp_lutin = client.get(f"/lutin/{tokens['alice']}")
    assert resp_lutin.status_code == 200
    assert "/admin" not in resp_lutin.text


# ==============================================================================
# Secret de session obligatoire : 404 furtif sinon (#87)
# ==============================================================================

LEGACY_DEFAULT_SECRET = "fremo-default-insecure-admin-secret"


def _app_without_secret(
    admin_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, secret: str | None
) -> TestClient:
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)
    app = create_admin_app(
        db_path=admin_db,
        res_dir=tmp_path,
        admin_password="secret_admin_test_password",
        admin_session_secret=secret,
    )
    return TestClient(app, base_url="https://testserver")


@pytest.mark.parametrize("secret", ["", None, "court", "x" * 31])
def test_admin_disabled_returns_stealth_404_without_valid_secret(
    admin_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, secret: str | None
) -> None:
    client = _app_without_secret(admin_db, tmp_path, monkeypatch, secret)
    funnel_body = client.get("/admin", headers={"Tailscale-Funnel-Request": "?1"}).text
    for method, path in [
        ("get", "/admin"),
        ("get", "/admin/login"),
        ("post", "/admin/login"),
        ("get", "/admin/logout"),
        ("post", "/admin/logout"),
    ]:
        resp = client.request(method, path, data={"password": "secret_admin_test_password"}, follow_redirects=False)
        assert resp.status_code == 404, (method, path)
        assert resp.text == funnel_body  # même gabarit erreur_404.html que la garde Funnel
        assert "set-cookie" not in resp.headers


def test_legacy_default_secret_cookie_is_rejected(
    admin_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ts = int(datetime.now(timezone.utc).timestamp())
    forged = create_session_token(LEGACY_DEFAULT_SECRET, "secret_admin_test_password", ts, ts)
    client = _app_without_secret(admin_db, tmp_path, monkeypatch, "")
    client.cookies.set(SESSION_COOKIE_NAME, forged)
    assert client.get("/admin", follow_redirects=False).status_code == 404

    app = create_admin_app(
        db_path=admin_db,
        admin_password="secret_admin_test_password",
        admin_session_secret="test_session_secret_at_least_32_bytes_long",
    )
    valid_client = TestClient(app, base_url="https://testserver")
    valid_client.cookies.set(SESSION_COOKIE_NAME, forged)
    resp = valid_client.get("/admin", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"


def test_admin_disabled_warning_logged_exactly_once(
    admin_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    client = _app_without_secret(admin_db, tmp_path, monkeypatch, "")
    client.get("/admin")
    client.get("/admin/login")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "admin_session_secret" in r.getMessage()]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "ADMIN_SESSION_SECRET" in msg
    assert "secrets.token_urlsafe(48)" in msg


def test_no_warning_when_secret_valid(admin_client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    assert not [r for r in caplog.records if "admin_session_secret" in r.getMessage()]


# ==============================================================================
# 6. Session révocable et durée de vie absolue (#90)
# ==============================================================================


def _login(client: TestClient) -> None:
    client.post("/admin/login", data={"password": "secret_admin_test_password"}, follow_redirects=False)


def test_session_token_refused_after_password_change(admin_db: Path, admin_client: TestClient) -> None:
    _login(admin_client)
    token = admin_client.cookies.get(SESSION_COOKIE_NAME)
    assert token is not None

    app_b = create_admin_app(
        db_path=admin_db,
        admin_password="another_password",
        admin_session_secret="test_session_secret_at_least_32_bytes_long",
    )
    client_b = TestClient(app_b, base_url="https://testserver")
    client_b.cookies.set(SESSION_COOKIE_NAME, token)
    resp = client_b.get("/admin", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"


def test_session_absolute_lifetime_12h_despite_hourly_activity(
    admin_client: TestClient, mutable_clock: list[datetime]
) -> None:
    _login(admin_client)
    for _ in range(11):
        mutable_clock[0] += timedelta(hours=1)
        assert admin_client.get("/admin", follow_redirects=False).status_code == 200
    mutable_clock[0] += timedelta(hours=1, seconds=1)
    resp = admin_client.get("/admin", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"


def test_sliding_renewal_keeps_issued_at(admin_client: TestClient, mutable_clock: list[datetime]) -> None:
    _login(admin_client)
    first = admin_client.cookies.get(SESSION_COOKIE_NAME)
    assert first is not None
    mutable_clock[0] += timedelta(hours=1)
    admin_client.get("/admin", follow_redirects=False)
    second = admin_client.cookies.get(SESSION_COOKIE_NAME)
    assert second is not None
    f_issued, f_seen, _ = first.split(".")
    s_issued, s_seen, _ = second.split(".")
    assert s_issued == f_issued
    assert int(s_seen) == int(f_seen) + 3600


def test_legacy_two_part_cookie_redirects_to_login(admin_client: TestClient, mutable_clock: list[datetime]) -> None:
    ts = int(mutable_clock[0].timestamp())
    sig = hmac.new(b"test_session_secret_at_least_32_bytes_long", str(ts).encode(), hashlib.sha256).hexdigest()
    admin_client.cookies.set(SESSION_COOKIE_NAME, f"{ts}.{sig}")
    resp = admin_client.get("/admin", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"
