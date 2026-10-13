from pathlib import Path

import pytest
from pere_noel_fremo.database import init_db
from pere_noel_fremo.tokens import create_or_get_token
from pere_noel_fremo.web import create_app
from starlette.testclient import TestClient


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "fremo_test.db"
    conn = init_db(db_file)
    with conn:
        conn.execute(
            "INSERT INTO lutins (id, fullname, email) VALUES ('fbonnet', 'François Bonnet', 'fb@example.com');"
        )
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('alacroix', 'Alice Lacroix', 'al@example.com');")
        conn.execute("INSERT INTO editions (year, status) VALUES (2025, 'draft');")
    conn.close()
    return db_file


@pytest.fixture
def client(test_db: Path) -> TestClient:
    app = create_app(db_path=test_db)
    return TestClient(app)


def test_root_redirects_to_scores(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/scores"


def test_espace_lutin_get_valid_token(client: TestClient, test_db: Path) -> None:
    token = create_or_get_token(test_db, "fbonnet", 2025)
    response = client.get(f"/lutin/{token}")
    assert response.status_code == 200
    assert "François Bonnet" in response.text
    assert "Confirmation de présence" in response.text


def test_espace_lutin_get_invalid_token(client: TestClient) -> None:
    response = client.get("/lutin/invalid-token-xyz")
    assert response.status_code == 404
    assert "Lien magique introuvable" in response.text


def test_toggle_presence_updates_database(client: TestClient, test_db: Path) -> None:
    token = create_or_get_token(test_db, "fbonnet", 2025)

    # Confirmation de présence: Oui
    resp_yes = client.post(f"/api/lutin/{token}/presence", json={"present": True})
    assert resp_yes.status_code == 200
    data_yes = resp_yes.json()
    assert data_yes["ok"] is True
    assert data_yes["present"] is True

    # Check page reflects presence
    page = client.get(f"/lutin/{token}")
    assert page.status_code == 200
    assert 'data-presence="true"' in page.text or "checked" in page.text

    # Bascule présence: Non
    resp_no = client.post(f"/api/lutin/{token}/presence", json={"present": False})
    assert resp_no.status_code == 200
    assert resp_no.json()["present"] is False

    # Check page reflects absence
    page_absent = client.get(f"/lutin/{token}")
    assert page_absent.status_code == 200
    assert 'data-presence="false"' in page_absent.text
    assert "Tu as indiqué être Absent" in page_absent.text


def test_toggle_presence_rejected_when_edition_locked(client: TestClient, test_db: Path) -> None:
    token = create_or_get_token(test_db, "fbonnet", 2025)

    # Lock edition (tirage effectué)
    conn = init_db(test_db)
    with conn:
        conn.execute("UPDATE editions SET status = 'drawn' WHERE year = 2025;")
    conn.close()

    # Verify UI reflects locked state
    page_locked = client.get(f"/lutin/{token}")
    assert page_locked.status_code == 200
    assert "verrouillé" in page_locked.text
    assert "btn-group" not in page_locked.text

    # Verify API rejects modifications
    resp = client.post(f"/api/lutin/{token}/presence", json={"present": True})
    assert resp.status_code == 403
    assert "verrouillé" in resp.json().get("detail", "").lower()


def test_public_scores_endpoint(client: TestClient) -> None:
    resp = client.get("/scores")
    assert resp.status_code == 200
    assert "Tableau des scores" in resp.text


def test_defi_de_la_luge_flow(client: TestClient, test_db: Path) -> None:
    from pere_noel_fremo.database import set_lutin_presence
    from pere_noel_fremo.defi import get_or_load_grille

    token = create_or_get_token(test_db, "fbonnet", 2025)

    # 1. Avant confirmation de présence, le défi n'est pas démarrable
    resp_start_unconfirmed = client.post(f"/api/lutin/{token}/defi/start")
    assert resp_start_unconfirmed.status_code == 403
    assert "confirmer" in resp_start_unconfirmed.json().get("detail", "").lower()

    # Confirmer présence
    set_lutin_presence(test_db, "fbonnet", 2025, present=True)

    # 2. Tenter de résoudre avant de démarrer -> Erreur 400
    grille = get_or_load_grille(2025)
    resp_solve_before_start = client.post(
        f"/api/lutin/{token}/defi/solve",
        json={"solution": grille["solution"]},
    )
    assert resp_solve_before_start.status_code == 400
    assert "démarré" in resp_solve_before_start.json().get("detail", "").lower()

    # Vérifier que la page présente bien l'encart d'avertissement et le temps estimé
    page_prep = client.get(f"/lutin/{token}")
    assert page_prep.status_code == 200
    assert "Défi du lutin malin" in page_prep.text
    assert "Temps estimé" in page_prep.text
    assert "check-ready" in page_prep.text

    # 3. Démarrer le défi
    resp_start = client.post(f"/api/lutin/{token}/defi/start")
    assert resp_start.status_code == 200
    data_start = resp_start.json()
    assert data_start["ok"] is True
    assert "pseudo_lugeur" in data_start
    assert data_start["started_at"] is not None

    # 4. Soumettre une mauvaise solution
    resp_solve_wrong = client.post(
        f"/api/lutin/{token}/defi/solve",
        json={"solution": {"Barnabé": {"luge": "Mauvaise", "friandise": "Fausse"}}},
    )
    assert resp_solve_wrong.status_code == 400
    assert resp_solve_wrong.json()["solved"] is False

    # 5. Soumettre la bonne solution
    resp_solve_ok = client.post(
        f"/api/lutin/{token}/defi/solve",
        json={"solution": grille["solution"]},
    )
    assert resp_solve_ok.status_code == 200
    data_solve = resp_solve_ok.json()
    assert data_solve["solved"] is True
    assert data_solve["time_seconds"] >= 0

    # 6. La page Espace Lutin affiche le statut résolu et le pseudo
    page = client.get(f"/lutin/{token}")
    assert page.status_code == 200
    assert data_start["pseudo_lugeur"] in page.text


def test_revelation_beneficiaire_carte_a_gratter(client: TestClient, test_db: Path) -> None:
    from pere_noel_fremo.database import save_attributions

    token = create_or_get_token(test_db, "fbonnet", 2025)

    # Avant le tirage au sort (status 'draft') :
    # 1. L'API refuse de révéler le bénéficiaire (403)
    resp_before_draw = client.get(f"/api/lutin/{token}/beneficiaire")
    assert resp_before_draw.status_code == 403

    # 2. La page HTML ne contient aucun nom de bénéficiaire ni l'élément canvas
    page_before_draw = client.get(f"/lutin/{token}")
    assert page_before_draw.status_code == 200
    assert "Alice Lacroix" not in page_before_draw.text
    assert '<canvas id="scratch-canvas"' not in page_before_draw.text

    # Tirage au sort effectué
    save_attributions(test_db, 2025, {"fbonnet": "alacroix", "alacroix": "fbonnet"})

    # Après le tirage : le bénéficiaire est disponible pour la carte à gratter
    resp_after_draw = client.get(f"/api/lutin/{token}/beneficiaire")
    assert resp_after_draw.status_code == 200
    beneficiaire_data = resp_after_draw.json()
    assert beneficiaire_data["fullname"] == "Alice Lacroix"

    # La page HTML contient maintenant la carte à gratter et le bouton revoir l'effet
    page_after_draw = client.get(f"/lutin/{token}")
    assert page_after_draw.status_code == 200
    assert "Alice Lacroix" in page_after_draw.text
    assert '<canvas id="scratch-canvas"' in page_after_draw.text
    assert "btn-re-scratch" in page_after_draw.text
    assert "resetScratch" in page_after_draw.text
    assert "paintScratchCover" in page_after_draw.text


def test_defi_multi_manches_api_flow(client: TestClient, test_db: Path) -> None:
    from pere_noel_fremo.database import set_lutin_presence
    from pere_noel_fremo.defi import get_manche

    token = create_or_get_token(test_db, "fbonnet", 2025)
    set_lutin_presence(test_db, "fbonnet", 2025, present=True)

    # 1. Erreurs 404 : Token inconnu ou Manche inconnue
    resp_bad_token = client.post("/api/lutin/token-inconnu-xyz/defi/1/start")
    assert resp_bad_token.status_code == 404

    resp_bad_manche = client.post(f"/api/lutin/{token}/defi/999/start")
    assert resp_bad_manche.status_code == 404

    m1 = get_manche(2025, 1)
    assert m1 is not None

    # 2. Démarrage manche 1
    resp_start_m1 = client.post(f"/api/lutin/{token}/defi/1/start")
    assert resp_start_m1.status_code == 200
    data_m1 = resp_start_m1.json()
    assert data_m1["ok"] is True
    assert data_m1["manche_id"] == 1
    assert data_m1["started_at"] is not None

    # 3. Résolution mauvaise solution sur manche 1 -> 400
    resp_solve_wrong = client.post(
        f"/api/lutin/{token}/defi/1/solve",
        json={"solution": {"Faux": {"luge": "X"}}},
    )
    assert resp_solve_wrong.status_code == 400
    assert resp_solve_wrong.json()["solved"] is False

    # 4. Résolution bonne solution sur manche 1 -> 200
    resp_solve_m1 = client.post(
        f"/api/lutin/{token}/defi/1/solve",
        json={"solution": m1["solution"]},
    )
    assert resp_solve_m1.status_code == 200
    res_data = resp_solve_m1.json()
    assert res_data["solved"] is True
    assert res_data["manche_id"] == 1
    assert res_data["time_seconds"] >= 0

    # 5. Tentative de redémarrer une manche déjà résolue -> 400 (essai unique officiel)
    resp_restart = client.post(f"/api/lutin/{token}/defi/1/start")
    assert resp_restart.status_code == 400
    assert "déjà été résolue" in resp_restart.json().get("detail", "").lower()

    # 6. Vérification de l'actualisation dynamique du classement en direct
    resp_scores = client.get("/scores/2025")
    assert resp_scores.status_code == 200
    assert data_m1["pseudo_lugeur"] in resp_scores.text


def test_locked_manche_refuses_start_and_solve(client: TestClient, test_db: Path) -> None:
    from pere_noel_fremo.database import set_lutin_presence

    # Édition 2026 où les manches ont un unlock_at futur (ex: 2026-10-16)
    conn = init_db(test_db)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
    conn.close()

    token_2026 = create_or_get_token(test_db, "fbonnet", 2026)
    set_lutin_presence(test_db, "fbonnet", 2026, present=True)

    # Manche 2 pour 2026 s'ouvre le 19/10/2026 (futur par rapport à la date de test) -> 403
    resp_start = client.post(f"/api/lutin/{token_2026}/defi/2/start")
    assert resp_start.status_code == 403
    assert "déverrouillée" in resp_start.json().get("detail", "").lower()

    # Tentative de résolution directe -> 403
    resp_solve = client.post(
        f"/api/lutin/{token_2026}/defi/2/solve",
        json={"solution": {}},
    )
    assert resp_solve.status_code == 403
    assert "déverrouillée" in resp_solve.json().get("detail", "").lower()


def test_scores_page_displays_championship_standings(client: TestClient, test_db: Path) -> None:
    from pere_noel_fremo.database import complete_score_defi, get_or_create_score_defi

    # Enregistrer des scores sur 2025
    get_or_create_score_defi(test_db, "fbonnet", 2025, "Renne Agile", manche_id=1)
    complete_score_defi(test_db, "fbonnet", 2025, time_seconds=32.4, manche_id=1)

    resp = client.get("/scores/2025")
    assert resp.status_code == 200
    assert "Tableau des scores" in resp.text
    assert "Renne Agile" in resp.text
    assert "32.4" in resp.text


def test_espace_lutin_multi_manches_and_anti_cheat_ui(client: TestClient, test_db: Path) -> None:
    from pere_noel_fremo.database import complete_score_defi, get_or_create_score_defi, set_lutin_presence

    # Test avec l'édition 2025 (1 manche)
    token = create_or_get_token(test_db, "fbonnet", 2025)
    set_lutin_presence(test_db, "fbonnet", 2025, present=True)

    page = client.get(f"/lutin/{token}")
    assert page.status_code == 200

    # 1. Calendrier des manches présent
    assert "manche" in page.text.lower()
    assert "manche-badge" in page.text
    assert "Manche #1" in page.text

    # 2. Rendu des indices via HTML5 Canvas (anti-OCR) et absence d'indices en clair dans le DOM
    assert '<canvas id="clue-canvas"' in page.text
    assert "anti-ocr" in page.text.lower()
    # Garantie anti-triche : aucun texte d'indice en clair dans le code HTML de la page
    assert "Barnabé ne conduit pas l'Étoile Rouge" not in page.text
    assert "OBF_CLUES" in page.text

    # 3. Fragmentation des indices par onglets (anti-screenshot global)
    assert "clue-tab" in page.text
    assert "tab-clue-0" in page.text

    # 4. Protection CSS / JS : zone anti-triche et rideau d'urgence sur blur
    assert 'class="anti-cheat-zone"' in page.text
    assert 'oncontextmenu="return false;"' in page.text
    assert 'id="emergency-curtain"' in page.text
    assert "dismissEmergencyCurtain" in page.text

    # 5. Profil championnat du lutin
    assert "championnat" in page.text.lower()
    assert "Points Grand Prix" in page.text
    assert "Écart au leader" in page.text

    # 6. Écran préparatoire de manche avec case à cocher explicite "Je suis prêt(e)"
    assert 'id="check-ready"' in page.text
    assert "Je suis prêt(e)" in page.text
    assert 'id="btn-start-defi"' in page.text

    # 7. Résolution et affichage du statut scellé
    get_or_create_score_defi(test_db, "fbonnet", 2025, "Renne Agile", manche_id=1)
    complete_score_defi(test_db, "fbonnet", 2025, time_seconds=42.5, manche_id=1)
    page_m1_solved = client.get(f"/lutin/{token}?manche=1")
    assert page_m1_solved.status_code == 200
    assert "42.5" in page_m1_solved.text
    assert "brillamment résolue" in page_m1_solved.text

    # 8. Test avec l'édition 2026 (15 manches de championnat)
    conn = init_db(test_db)
    with conn:
        conn.execute("INSERT OR IGNORE INTO editions (year, status) VALUES (2026, 'draft');")
    conn.close()

    token_2026 = create_or_get_token(test_db, "fbonnet", 2026)
    set_lutin_presence(test_db, "fbonnet", 2026, present=True)

    page_2026 = client.get(f"/lutin/{token_2026}")
    assert page_2026.status_code == 200
    assert "Calendrier des Manches (15)" in page_2026.text
    assert "Manche #1" in page_2026.text
    assert "Manche #2" in page_2026.text
    assert "Manche #15" in page_2026.text

    # Navigation vers Manche #2
    page_2026_m2 = client.get(f"/lutin/{token_2026}?manche=2")
    assert page_2026_m2.status_code == 200
    assert "Manche #2" in page_2026_m2.text

    # 9. Feuilles de style responsives mobile et desktop
    css_resp = client.get("/static/style.css")
    assert css_resp.status_code == 200
    assert "@media (max-width: 640px)" in css_resp.text
    assert ".clue-canvas" in css_resp.text
    assert ".manches-grid" in css_resp.text


def test_abandon_defi_flow(client: TestClient, test_db: Path) -> None:
    token = create_or_get_token(test_db, "alacroix", 2025)
    client.post(f"/api/lutin/{token}/presence", json={"present": True})

    # Abandonner avant le démarrage doit échouer (400)
    resp_bad = client.post(f"/api/lutin/{token}/defi/1/abandon")
    assert resp_bad.status_code == 400
    assert "démarré avant" in resp_bad.json()["detail"]

    # Démarrage
    resp_start = client.post(f"/api/lutin/{token}/defi/1/start")
    assert resp_start.status_code == 200

    # Abandon
    resp_abandon = client.post(f"/api/lutin/{token}/defi/1/abandon")
    assert resp_abandon.status_code == 200
    assert resp_abandon.json()["abandoned"] is True

    # Vérification que la page affiche le statut abandonné
    page = client.get(f"/lutin/{token}?manche=1")
    assert page.status_code == 200
    assert "Tu as abandonné la Manche #1" in page.text
    assert "🏳️ Abandonnée" in page.text
    assert "let isCompleted = true;" in page.text
    assert "let isChallengeActive = isStarted && !isCompleted;" in page.text

    # Impossible de relancer la manche après abandon (essai unique officiel)
    resp_restart = client.post(f"/api/lutin/{token}/defi/1/start")
    assert resp_restart.status_code == 400
    assert "abandonnée" in resp_restart.json()["detail"]

    # Impossible de résoudre après abandon
    resp_solve = client.post(
        f"/api/lutin/{token}/defi/1/solve",
        json={"solution": {}},
    )
    assert resp_solve.status_code == 400
    assert "terminée" in resp_solve.json()["detail"]
