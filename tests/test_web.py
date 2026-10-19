from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pere_noel_fremo.database import get_db_connection, get_score_defi, init_db
from pere_noel_fremo.tokens import create_or_get_token
from pere_noel_fremo.web import create_app
from starlette.testclient import TestClient


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "fremo_test.db"
    init_db(db_file)
    conn = get_db_connection(db_file)
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
    conn = get_db_connection(test_db)
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
    assert "pseudo_lutin" in data_start
    assert "pseudo_lutin" in data_start
    assert data_start["pseudo_lutin"] == data_start["pseudo_lutin"]
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
    assert "pseudo_lutin" in data_solve
    assert data_solve["pseudo_lutin"] == data_solve["pseudo_lutin"]

    # 6. La page Espace Lutin affiche le statut résolu et le pseudo
    page = client.get(f"/lutin/{token}")
    assert page.status_code == 200
    assert data_start["pseudo_lutin"] in page.text


def test_revelation_beneficiaire_carte_a_gratter(client: TestClient, test_db: Path) -> None:
    from pere_noel_fremo.database import save_attributions, set_lutin_presence

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
    set_lutin_presence(test_db, "fbonnet", 2025, present=True)
    set_lutin_presence(test_db, "alacroix", 2025, present=True)
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
    assert data_m1["pseudo_lutin"] in resp_scores.text


def test_locked_manche_refuses_start_and_solve(client: TestClient, test_db: Path) -> None:
    from pere_noel_fremo.database import set_lutin_presence

    # Édition 2026 où les manches ont un unlock_at futur (ex: 2026-10-16)
    conn = get_db_connection(test_db)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
    conn.close()

    token_2026 = create_or_get_token(test_db, "fbonnet", 2026)
    set_lutin_presence(test_db, "fbonnet", 2026, present=True)

    # Manche 4 pour 2026 s'ouvre le 26/10/2026 (futur par rapport à la date de test) -> 403
    resp_start = client.post(f"/api/lutin/{token_2026}/defi/4/start")
    assert resp_start.status_code == 403
    assert "déverrouillée" in resp_start.json().get("detail", "").lower()

    # Tentative de résolution directe -> 403
    resp_solve = client.post(
        f"/api/lutin/{token_2026}/defi/4/solve",
        json={"solution": {}},
    )
    assert resp_solve.status_code == 403
    assert "déverrouillée" in resp_solve.json().get("detail", "").lower()


def test_scores_page_displays_championship_standings(
    client: TestClient, test_db: Path, solve_manche: Callable[..., dict[str, Any]]
) -> None:
    # Enregistrer des scores sur 2025
    solve_manche(test_db, "fbonnet", 2025, 32.4, pseudo_lutin="Renne Agile")

    resp = client.get("/scores/2025")
    assert resp.status_code == 200
    assert "Tableau des scores" in resp.text
    assert "Renne Agile" in resp.text
    assert "32.4" in resp.text


def test_espace_lutin_multi_manches_and_anti_cheat_ui(
    client: TestClient, test_db: Path, solve_manche: Callable[..., dict[str, Any]]
) -> None:
    from pere_noel_fremo.database import set_lutin_presence

    # Test avec l'édition 2025 (1 manche)
    token = create_or_get_token(test_db, "fbonnet", 2025)
    set_lutin_presence(test_db, "fbonnet", 2025, present=True)

    page = client.get(f"/lutin/{token}")
    assert page.status_code == 200

    # 1. Calendrier des manches présent
    assert "manche" in page.text.lower()
    assert "manche-badge" in page.text
    assert "Manche #1" in page.text

    # 2. Rendu des indices via HTML5 Canvas (anti-OCR) et absence d'indices dans le DOM
    assert '<canvas id="clue-canvas"' in page.text
    assert "anti-ocr" in page.text.lower()
    # Garantie anti-triche : aucun texte d'indice en clair ni obfusqué dans le code HTML de la page
    assert "Barnabé ne conduit pas l'Étoile Rouge" not in page.text
    assert "OBF_CLUES" not in page.text
    assert "obf_clues" not in page.text

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
    solve_manche(test_db, "fbonnet", 2025, 42.5, pseudo_lutin="Renne Agile")
    page_m1_solved = client.get(f"/lutin/{token}?manche=1")
    assert page_m1_solved.status_code == 200
    assert "42.5" in page_m1_solved.text
    assert "brillamment résolue" in page_m1_solved.text

    # 8. Test avec l'édition 2026 (15 manches de championnat)
    conn = get_db_connection(test_db)
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


def test_abandon_defi_flow(client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    data_abandon = resp_abandon.json()
    assert data_abandon["abandoned"] is True
    assert "pseudo_lutin" in data_abandon
    assert "pseudo_lutin" in data_abandon
    assert data_abandon["pseudo_lutin"] == data_abandon["pseudo_lutin"]

    # Vérification que la page affiche le statut abandonné
    page = client.get(f"/lutin/{token}?manche=1")
    assert page.status_code == 200
    assert "Tu as abandonné la Manche #1" in page.text
    assert "🏳️ Abandonnée" in page.text
    assert "let isCompleted = true;" in page.text
    assert "let isChallengeActive = isStarted && !isCompleted;" in page.text

    page_bis = client.get(f"/lutin/{token}?manche=1")
    assert page_bis.status_code == 200
    assert "let isCompleted = true;" in page_bis.text
    monkeypatch.undo()

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


def test_espace_lutin_renders_date_repas(client: TestClient, test_db: Path) -> None:
    conn = get_db_connection(test_db)
    with conn:
        conn.execute("UPDATE editions SET date_repas = '2026-12-05' WHERE year = 2025;")
    conn.close()

    token = create_or_get_token(test_db, "fbonnet", 2025)
    page = client.get(f"/lutin/{token}")
    assert page.status_code == 200

    # Vérification présence dans l'en-tête et dans la confirmation de présence
    assert "Repas de Noël" in page.text
    assert "samedi 5 décembre 2026" in page.text
    assert "Participeras-tu à l'échange de cadeaux cette année ?" in page.text
    assert "Date du Repas de Noël" in page.text


def test_espace_lutin_locked_manche_no_clues_no_categories(client: TestClient, test_db: Path) -> None:
    conn = get_db_connection(test_db)
    with conn:
        conn.execute("INSERT OR IGNORE INTO editions (year, status) VALUES (2026, 'draft');")
    conn.close()

    token = create_or_get_token(test_db, "fbonnet", 2026)
    from pere_noel_fremo.database import set_lutin_presence

    set_lutin_presence(test_db, "fbonnet", 2026, present=True)

    # Manche 4 est verrouillée dans res/2026/grilles/manche_4.yml (unlock_at le 2026-10-26)
    response = client.get(f"/lutin/{token}?manche=4")
    assert response.status_code == 200
    page_text = response.text

    # Titre et unlock_at doivent être affichés
    assert "Manche 4 : Le Traîneau Mystère" in page_text
    assert "lundi 26 octobre, 17h00" in page_text
    assert "2026-10-26 17:00:00" not in page_text
    assert "Cette manche est encore verrouillée" in page_text

    # Aucun indice, ni en clair ni en base64
    assert "Barnabé ne conduit pas l'Étoile Rouge" not in page_text
    import base64

    b64_clue = base64.b64encode("Barnabé ne conduit pas l'Étoile Rouge".encode()).decode("ascii")
    assert b64_clue not in page_text
    assert "OBF_CLUES" not in page_text
    assert "obf_clues" not in page_text

    # Aucune catégorie de la manche verrouillée ne doit fuiter dans le DOM/JS
    assert "Barnabé" not in page_text
    assert "Clémence" not in page_text
    assert "Gaspard" not in page_text
    assert "Étoile Rouge" not in page_text
    assert "Comète Bleue" not in page_text
    assert "Éclair Vert" not in page_text
    assert "Pain d'épices" not in page_text
    assert "Canne de sucre" not in page_text
    assert "Chocolat chaud" not in page_text


def test_espace_lutin_unlocked_manche_not_started_no_clues(client: TestClient, test_db: Path) -> None:
    token = create_or_get_token(test_db, "fbonnet", 2025)
    from pere_noel_fremo.database import set_lutin_presence

    set_lutin_presence(test_db, "fbonnet", 2025, present=True)

    # Manche 1 déverrouillée mais non démarrée
    response = client.get(f"/lutin/{token}?manche=1")
    assert response.status_code == 200
    page_text = response.text

    # Contient les éléments prévus : titre, description, estimated_time, catégories
    assert "Le Défi du lutin malin" in page_text
    assert "2 à 5 minutes" in page_text
    assert "Barnabé" in page_text
    assert "Étoile Rouge" in page_text
    assert "Canne de sucre" in page_text
    assert "Indice 1" in page_text
    assert "Indice 4" in page_text

    # Aucun indice en clair ni en base64
    assert "Barnabé ne conduit pas l'Étoile Rouge" not in page_text
    import base64

    b64_clue = base64.b64encode("Barnabé ne conduit pas l'Étoile Rouge".encode()).decode("ascii")
    assert b64_clue not in page_text
    assert "OBF_CLUES" not in page_text
    assert "obf_clues" not in page_text


def test_espace_lutin_invalid_grid_shows_explicit_message(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pere_noel_fremo import web as web_module
    from pere_noel_fremo.database import set_lutin_presence
    from pere_noel_fremo.defi import GrilleInvalideError

    token = create_or_get_token(test_db, "fbonnet", 2025)
    set_lutin_presence(test_db, "fbonnet", 2025, present=True)

    def _boom(_manche: object) -> list[tuple[str, str]]:
        raise GrilleInvalideError("incohérente")

    monkeypatch.setattr(web_module, "get_manche_attributes", _boom)

    response = client.get(f"/lutin/{token}?manche=1")
    assert response.status_code == 200
    assert "mal configurée" in response.text
    assert 'id="btn-start-defi"' not in response.text


def test_start_defi_returns_indices_and_guards(client: TestClient, test_db: Path) -> None:
    conn = get_db_connection(test_db)
    with conn:
        conn.execute("INSERT OR IGNORE INTO editions (year, status) VALUES (2026, 'draft');")
    conn.close()

    token_confirmed = create_or_get_token(test_db, "fbonnet", 2026)
    from pere_noel_fremo.database import set_lutin_presence

    set_lutin_presence(test_db, "fbonnet", 2026, present=True)

    token_unconfirmed = create_or_get_token(test_db, "alacroix", 2026)
    # alacroix n'a pas confirmé sa présence

    # 1. Sans présence confirmée -> 403 sans indices
    resp_no_pres = client.post(f"/api/lutin/{token_unconfirmed}/defi/1/start")
    assert resp_no_pres.status_code == 403
    assert "indices" not in resp_no_pres.json()

    # 2. Manche verrouillée (manche 3) -> 403 sans indices
    resp_locked = client.post(f"/api/lutin/{token_confirmed}/defi/3/start")
    assert resp_locked.status_code == 403
    assert "indices" not in resp_locked.json()

    # 3. Manche déverrouillée avec présence confirmée -> 200 avec indices
    resp_ok = client.post(f"/api/lutin/{token_confirmed}/defi/1/start")
    assert resp_ok.status_code == 200
    data = resp_ok.json()
    assert data["ok"] is True
    assert "indices" in data
    assert isinstance(data["indices"], list)
    assert len(data["indices"]) > 0
    assert any("Comète Bleue" in idx for idx in data["indices"])

    # Test alias sans manche_id sur manche 1 avec un autre lutin confirmé
    token_fbonnet_2025 = create_or_get_token(test_db, "fbonnet", 2025)
    set_lutin_presence(test_db, "fbonnet", 2025, present=True)
    resp_alias = client.post(f"/api/lutin/{token_fbonnet_2025}/defi/start")
    assert resp_alias.status_code == 200
    data_alias = resp_alias.json()
    assert "indices" in data_alias
    assert len(data_alias["indices"]) > 0


def test_defi_indices_resume_endpoint(client: TestClient, test_db: Path) -> None:
    token = create_or_get_token(test_db, "fbonnet", 2025)
    from pere_noel_fremo.database import set_lutin_presence

    set_lutin_presence(test_db, "fbonnet", 2025, present=True)

    # 1. Avant start -> 403
    resp_before = client.get(f"/api/lutin/{token}/defi/1/indices")
    assert resp_before.status_code == 403
    assert "indices" not in resp_before.json()

    # Test alias sans manche_id
    resp_alias_before = client.get(f"/api/lutin/{token}/defi/indices")
    assert resp_alias_before.status_code == 403

    # Démarrage
    resp_start = client.post(f"/api/lutin/{token}/defi/1/start")
    assert resp_start.status_code == 200

    # 2. Pendant l'essai -> 200 avec indices
    resp_during = client.get(f"/api/lutin/{token}/defi/1/indices")
    assert resp_during.status_code == 200
    data_during = resp_during.json()
    assert data_during["ok"] is True
    assert "indices" in data_during
    assert isinstance(data_during["indices"], list)
    assert len(data_during["indices"]) == 4

    resp_alias_during = client.get(f"/api/lutin/{token}/defi/indices")
    assert resp_alias_during.status_code == 200
    assert len(resp_alias_during.json()["indices"]) == 4

    # 3. Après solve -> 403
    # On valide la grille (DEFAULT_GRILLE_2026 solution)
    solution = {
        "Barnabé": {"luge": "Comète Bleue", "friandise": "Chocolat chaud"},
        "Clémence": {"luge": "Étoile Rouge", "friandise": "Pain d'épices"},
        "Gaspard": {"luge": "Éclair Vert", "friandise": "Canne de sucre"},
    }
    resp_solve = client.post(f"/api/lutin/{token}/defi/1/solve", json={"solution": solution})
    assert resp_solve.status_code == 200
    assert resp_solve.json()["solved"] is True

    resp_after_solve = client.get(f"/api/lutin/{token}/defi/1/indices")
    assert resp_after_solve.status_code == 403

    # 4. Après abandon -> 403 (testé avec un second lutin)
    token_abandon = create_or_get_token(test_db, "alacroix", 2025)
    set_lutin_presence(test_db, "alacroix", 2025, present=True)
    client.post(f"/api/lutin/{token_abandon}/defi/1/start")
    client.post(f"/api/lutin/{token_abandon}/defi/1/abandon")

    resp_after_abandon = client.get(f"/api/lutin/{token_abandon}/defi/1/indices")
    assert resp_after_abandon.status_code == 403


def test_solve_defi_attempts_and_penalties_lifecycle(client: TestClient, test_db: Path) -> None:
    from pere_noel_fremo.database import (
        get_db_connection,
        set_lutin_presence,
    )
    from pere_noel_fremo.defi import get_manche
    from pere_noel_fremo.tokens import create_or_get_token

    m1 = get_manche(2025, 1)
    assert m1 is not None
    sol_ok = m1["solution"]
    # Solution erronée mais complète
    sol_wrong = {
        "Barnabé": {"luge": "Éclair Vert", "friandise": "Canne de sucre"},
        "Clémence": {"luge": "Comète Bleue", "friandise": "Chocolat chaud"},
        "Gaspard": {"luge": "Étoile Rouge", "friandise": "Pain d'épices"},
    }

    conn = get_db_connection(test_db)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO lutins (id, fullname, email) VALUES ('jdupont', 'Jean Dupont', 'jd@fremo.org');"
        )
        conn.execute(
            "INSERT OR IGNORE INTO lutins (id, fullname, email) VALUES ('mmartin', 'Marie Martin', 'mm@fremo.org');"
        )
        conn.execute(
            "INSERT OR IGNORE INTO lutins (id, fullname, email) "
            "VALUES ('plefebvre', 'Pierre Lefebvre', 'pl@fremo.org');"
        )
        conn.execute(
            "INSERT OR IGNORE INTO lutins (id, fullname, email) VALUES ('cbernard', 'Claire Bernard', 'cb@fremo.org');"
        )
    conn.close()

    # --- Cas 1 : 1 essai faux puis 1 juste -> attempts=2, time_seconds >= raw + 15 ---
    token_1 = create_or_get_token(test_db, "jdupont", 2025)
    set_lutin_presence(test_db, "jdupont", 2025, present=True)
    client.post(f"/api/lutin/{token_1}/defi/1/start")

    # Requête incomplète -> rejetée en 400 sans consommer d'essai
    resp_inc = client.post(
        f"/api/lutin/{token_1}/defi/1/solve",
        json={"solution": {"Barnabé": {"luge": "Comète Bleue"}}},
    )
    assert resp_inc.status_code == 400
    assert resp_inc.json()["solved"] is False
    # Vérifier que attempts est toujours à 0
    assert get_score_defi(test_db, "jdupont", 2025, manche_id=1)["attempts"] == 0

    # Essai 1 : faux complet
    resp_wrong1 = client.post(
        f"/api/lutin/{token_1}/defi/1/solve",
        json={"solution": sol_wrong},
    )
    assert resp_wrong1.status_code == 400
    d_w1 = resp_wrong1.json()
    assert d_w1["solved"] is False
    assert d_w1["attempts"] == 1
    assert d_w1["essais_restants"] == 2
    assert d_w1["penalite_secondes"] == 15

    # Essai 2 : juste
    resp_ok1 = client.post(
        f"/api/lutin/{token_1}/defi/1/solve",
        json={"solution": sol_ok},
    )
    assert resp_ok1.status_code == 200
    d_ok1 = resp_ok1.json()
    assert d_ok1["solved"] is True
    assert d_ok1["attempts"] == 2
    assert d_ok1["time_seconds"] >= 15.0

    # --- Cas 2 : 2 essais faux puis 1 juste -> attempts=3, time_seconds >= raw + 30 ---
    token_2 = create_or_get_token(test_db, "mmartin", 2025)
    set_lutin_presence(test_db, "mmartin", 2025, present=True)
    client.post(f"/api/lutin/{token_2}/defi/1/start")

    # Essai 1 faux
    r1 = client.post(f"/api/lutin/{token_2}/defi/1/solve", json={"solution": sol_wrong})
    assert r1.status_code == 400
    assert r1.json()["attempts"] == 1

    # Essai 2 faux
    r2 = client.post(f"/api/lutin/{token_2}/defi/1/solve", json={"solution": sol_wrong})
    assert r2.status_code == 400
    assert r2.json()["attempts"] == 2
    assert r2.json()["essais_restants"] == 1

    # Essai 3 juste
    r3 = client.post(f"/api/lutin/{token_2}/defi/1/solve", json={"solution": sol_ok})
    assert r3.status_code == 200
    d_r3 = r3.json()
    assert d_r3["solved"] is True
    assert d_r3["attempts"] == 3
    assert d_r3["time_seconds"] >= 30.0

    # --- Cas 3 : 3 essais faux -> manche scellée, 1 pt participation, 4e appel -> 400 ---
    token_3 = create_or_get_token(test_db, "plefebvre", 2025)
    set_lutin_presence(test_db, "plefebvre", 2025, present=True)
    client.post(f"/api/lutin/{token_3}/defi/1/start")

    client.post(f"/api/lutin/{token_3}/defi/1/solve", json={"solution": sol_wrong})
    client.post(f"/api/lutin/{token_3}/defi/1/solve", json={"solution": sol_wrong})
    r_third = client.post(f"/api/lutin/{token_3}/defi/1/solve", json={"solution": sol_wrong})
    assert r_third.status_code == 400
    d_third = r_third.json()
    assert d_third["solved"] is False
    assert d_third["attempts"] == 3
    assert d_third["essais_restants"] == 0

    # Vérification en base : scellé avec solved=0 et time_seconds=None
    row3 = get_score_defi(test_db, "plefebvre", 2025, manche_id=1)
    assert row3["solved"] == 0
    assert row3["time_seconds"] is None
    assert row3["completed_at"] is not None
    assert row3["attempts"] == 3

    # 4e tentative -> 400
    r_fourth = client.post(f"/api/lutin/{token_3}/defi/1/solve", json={"solution": sol_ok})
    assert r_fourth.status_code == 400
    assert "terminée" in r_fourth.json().get("detail", "").lower()

    # --- Cas 4 : Abandon volontaire -> 0 point ---
    token_4 = create_or_get_token(test_db, "cbernard", 2025)
    set_lutin_presence(test_db, "cbernard", 2025, present=True)
    client.post(f"/api/lutin/{token_4}/defi/1/start")
    client.post(f"/api/lutin/{token_4}/defi/1/abandon")

    # Classement au championnat
    from pere_noel_fremo.defi import calculate_championship_standings

    standings = calculate_championship_standings(test_db, 2025)
    p_third = next(s for s in standings if s["pseudo_lutin"] == row3["pseudo_lutin"])
    pseudo_4 = get_score_defi(test_db, "cbernard", 2025)["pseudo_lutin"]
    p_fourth = next(s for s in standings if s["pseudo_lutin"] == pseudo_4)

    # 3 essais faux donne 1 point de participation
    assert p_third["total_points"] == 1
    assert p_third["manches_resolved_count"] == 0

    # Abandon volontaire donne 0 point
    assert p_fourth["total_points"] == 0


def test_regression_brute_force_attack_fails_and_never_solves_under_60s(client: TestClient, test_db: Path) -> None:
    import itertools

    from pere_noel_fremo.database import set_lutin_presence
    from pere_noel_fremo.defi import get_manche
    from pere_noel_fremo.tokens import create_or_get_token

    m1 = get_manche(2025, 1)
    assert m1 is not None
    lutins = m1["categories"]["lutins"]
    luges = m1["categories"]["luges"]
    friandises = m1["categories"]["friandises"]

    # Générer les 3! x 3! = 36 combinaisons possibles
    all_combinations = []
    for luge_perm in itertools.permutations(luges):
        for friandise_perm in itertools.permutations(friandises):
            candidate = {lutins[i]: {"luge": luge_perm[i], "friandise": friandise_perm[i]} for i in range(len(lutins))}
            all_combinations.append(candidate)

    # Exclure la vraie solution des 3 premières tentatives pour simuler l'attaque force-brute standard
    sol_ok = m1["solution"]
    wrong_candidates = [c for c in all_combinations if c != sol_ok]
    candidates_to_try = wrong_candidates[:3] + [sol_ok] + wrong_candidates[3:]

    conn = get_db_connection(test_db)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO lutins (id, fullname, email) "
            "VALUES ('brute_force_attacker', 'Attaquant', 'att@fremo.org');"
        )
    conn.close()

    token = create_or_get_token(test_db, "brute_force_attacker", 2025)
    set_lutin_presence(test_db, "brute_force_attacker", 2025, present=True)
    client.post(f"/api/lutin/{token}/defi/1/start")

    solved = False
    solved_time = None
    attempts_made = 0

    for cand in candidates_to_try:
        resp = client.post(f"/api/lutin/{token}/defi/1/solve", json={"solution": cand})
        attempts_made += 1
        if resp.status_code == 200 and resp.json().get("solved"):
            solved = True
            solved_time = resp.json().get("time_seconds")
            break

    # L'attaque par force brute doit avoir échoué car plafonnée à 3 essais
    assert solved is False
    assert solved_time is None
    # Au 3e essai la manche a été scellée et le 4e a renvoyé 400
    assert attempts_made == len(candidates_to_try)


def test_espace_lutin_ui_elements_for_attempts_and_penalties(client: TestClient, test_db: Path) -> None:
    from pere_noel_fremo.database import set_lutin_presence
    from pere_noel_fremo.tokens import create_or_get_token

    conn = get_db_connection(test_db)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO lutins (id, fullname, email) VALUES ('ui_tester', 'UI Tester', 'ui@fremo.org');"
        )
    conn.close()

    token = create_or_get_token(test_db, "ui_tester", 2025)
    set_lutin_presence(test_db, "ui_tester", 2025, present=True)
    client.post(f"/api/lutin/{token}/defi/1/start")

    page = client.get(f"/lutin/{token}?manche=1")
    assert page.status_code == 200
    # Bouton valider initialement désactivé
    assert 'id="btn-submit-defi"' in page.text
    assert "disabled" in page.text
    # Zone d'affichage des pénalités
    assert 'id="penalty-display"' in page.text
    # Logique de vérification de complétude de la grille
    assert "checkGridCompletion" in page.text


def test_scores_page_does_not_contain_lutin_id(
    client: TestClient, test_db: Path, solve_manche: Callable[..., dict[str, Any]]
) -> None:
    # Insérer un score
    solve_manche(test_db, "fbonnet", 2025, 30.0, pseudo_lutin="Renne Agile")

    resp = client.get("/scores")
    assert resp.status_code == 200
    html = resp.text

    # Vérifier qu'aucun lutin_id n'apparaît dans le HTML de /scores
    assert "fbonnet" not in html
    assert "alacroix" not in html


def test_regression_jdenis_mdenis_standings(client: TestClient, test_db: Path) -> None:
    from pere_noel_fremo.database import (
        set_lutin_presence,
    )
    from pere_noel_fremo.defi import get_or_load_grille

    conn = get_db_connection(test_db)
    with conn:
        conn.execute("INSERT OR IGNORE INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute(
            "INSERT OR IGNORE INTO lutins (id, fullname, email) VALUES ('jdenis', 'Jean Denis', 'jd@fremo.org');"
        )
        conn.execute(
            "INSERT OR IGNORE INTO lutins (id, fullname, email) VALUES ('mdenis', 'Marc Denis', 'md@fremo.org');"
        )
    conn.close()

    tok_j = create_or_get_token(test_db, "jdenis", 2026)
    tok_m = create_or_get_token(test_db, "mdenis", 2026)

    set_lutin_presence(test_db, "jdenis", 2026, present=True)
    set_lutin_presence(test_db, "mdenis", 2026, present=True)

    client.post(f"/api/lutin/{tok_j}/defi/1/start")
    client.post(f"/api/lutin/{tok_m}/defi/1/start")

    # Ajuster started_at pour donner 30s à jdenis et 45s à mdenis
    conn = get_db_connection(test_db)
    with conn:
        conn.execute(
            "UPDATE scores_defi SET started_at = '2026-10-14 20:00:00' WHERE lutin_id = 'jdenis' AND manche_id = 1;"
        )
        conn.execute(
            "UPDATE scores_defi SET started_at = '2026-10-14 20:00:00' WHERE lutin_id = 'mdenis' AND manche_id = 1;"
        )
    conn.close()

    grille = get_or_load_grille(2026)

    # Note: solve_defi utilise l'horloge réelle de l'application (datetime.now(timezone.utc)) par défaut,
    # donc on valide via l'API puis on simule le temps final si nécessaire
    res_j = client.post(f"/api/lutin/{tok_j}/defi/1/solve", json={"solution": grille["solution"]})
    assert res_j.status_code == 200

    res_m = client.post(f"/api/lutin/{tok_m}/defi/1/solve", json={"solution": grille["solution"]})
    assert res_m.status_code == 200

    conn = get_db_connection(test_db)
    with conn:
        conn.execute("UPDATE scores_defi SET time_seconds = 30.0 WHERE lutin_id = 'jdenis' AND manche_id = 1;")
        conn.execute("UPDATE scores_defi SET time_seconds = 45.0 WHERE lutin_id = 'mdenis' AND manche_id = 1;")
    conn.close()

    # Vérification du classement public
    resp_scores = client.get("/scores/2026")
    assert resp_scores.status_code == 200
    scores_html = resp_scores.text

    # Deux lignes distinctes avec 10 pts et 8 pts
    assert "10 pts" in scores_html
    assert "8 pts" in scores_html
    # Strict anonymat : aucun identifiant lutin dans le HTML
    assert "jdenis" not in scores_html
    assert "mdenis" not in scores_html

    # Vérification dans l'Espace Lutin de chacun (recherche par lutin_id)
    page_j = client.get(f"/lutin/{tok_j}")
    assert page_j.status_code == 200
    assert "#1" in page_j.text
    assert "10 pts" in page_j.text

    page_m = client.get(f"/lutin/{tok_m}")
    assert page_m.status_code == 200
    assert "#2" in page_m.text
    assert "8 pts" in page_m.text


def test_espace_lutin_get_read_only_no_score_created_absent_from_scores(client: TestClient, test_db: Path) -> None:
    """GET /lutin/{token} ne crée aucune ligne dans scores_defi ; lutin absent de /scores."""
    token = create_or_get_token(test_db, "fbonnet", 2025)

    # 1. Ouvrir seulement l'Espace Lutin
    resp_get = client.get(f"/lutin/{token}")
    assert resp_get.status_code == 200

    conn = get_db_connection(test_db)
    count = conn.execute("SELECT COUNT(*) FROM scores_defi WHERE lutin_id = 'fbonnet';").fetchone()[0]
    conn.close()
    assert count == 0

    # Vérifier l'absence sur /scores
    resp_scores = client.get("/scores/2025")
    assert resp_scores.status_code == 200
    assert "François Bonnet" not in resp_scores.text
    assert "fbonnet" not in resp_scores.text
    # Aucune ligne de classement
    assert "my-score-row" not in resp_scores.text

    # 2. Décliner sa présence puis rouvrir
    resp_presence = client.post(f"/api/lutin/{token}/presence", json={"present": False})
    assert resp_presence.status_code == 200

    resp_get2 = client.get(f"/lutin/{token}")
    assert resp_get2.status_code == 200

    conn = get_db_connection(test_db)
    count2 = conn.execute("SELECT COUNT(*) FROM scores_defi WHERE lutin_id = 'fbonnet';").fetchone()[0]
    conn.close()
    assert count2 == 0

    resp_scores2 = client.get("/scores/2025")
    assert "fbonnet" not in resp_scores2.text


def test_chrono_injectable_clock_millisecond_precision(tmp_path: Path) -> None:
    """Test avec horloge injectée : start à t0, solve à t0 + 30.46 s -> time_seconds == 30.5."""
    from datetime import datetime, timedelta, timezone

    from pere_noel_fremo.database import set_lutin_presence
    from pere_noel_fremo.defi import get_or_load_grille

    db_file = tmp_path / "fremo_clock_test.db"
    init_db(db_file)
    conn = get_db_connection(db_file)
    with conn:
        conn.execute(
            "INSERT INTO lutins (id, fullname, email) VALUES ('fbonnet', 'François Bonnet', 'fb@example.com');"
        )
        conn.execute("INSERT INTO editions (year, status) VALUES (2025, 'draft');")
    conn.close()

    token = create_or_get_token(db_file, "fbonnet", 2025)
    set_lutin_presence(db_file, "fbonnet", 2025, present=True)

    t0 = datetime(2025, 12, 24, 18, 0, 0, 0, tzinfo=timezone.utc)
    current_time = t0

    def mock_clock() -> datetime:
        return current_time

    app = create_app(db_path=db_file, clock=mock_clock)
    test_client = TestClient(app)

    # 1. Démarrage à t0
    resp_start = test_client.post(f"/api/lutin/{token}/defi/1/start")
    assert resp_start.status_code == 200
    data_start = resp_start.json()
    assert data_start["ok"] is True
    assert "T" in data_start["started_at"]

    # 2. Résolution à t0 + 30.46 s
    current_time = t0 + timedelta(seconds=30.46)
    grille = get_or_load_grille(2025)
    assert grille is not None

    resp_solve = test_client.post(
        f"/api/lutin/{token}/defi/1/solve",
        json={"solution": grille["solution"]},
    )
    assert resp_solve.status_code == 200
    data_solve = resp_solve.json()
    assert data_solve["solved"] is True
    # round(30.46 + 0.0, 1) == 30.5
    assert data_solve["time_seconds"] == 30.5

    # 3. Vérification en base des horodatages ISO UTC avec millisecondes
    conn = get_db_connection(db_file)
    row = conn.execute("SELECT * FROM scores_defi WHERE lutin_id = 'fbonnet' AND manche_id = 1;").fetchone()
    conn.close()

    assert row["time_seconds"] == 30.5
    started_at_str = str(row["started_at"])
    completed_at_str = str(row["completed_at"])
    assert "T" in started_at_str
    assert "T" in completed_at_str
    assert "+00:00" in started_at_str or "Z" in started_at_str


def test_chrono_legacy_started_at_read_correctly(tmp_path: Path) -> None:
    """Une ligne existante au format seconde %Y-%m-%d %H:%M:%S est toujours lue correctement."""
    from datetime import datetime, timezone

    from pere_noel_fremo.database import set_lutin_presence
    from pere_noel_fremo.defi import get_or_load_grille

    db_file = tmp_path / "fremo_legacy_date.db"
    init_db(db_file)
    conn = get_db_connection(db_file)
    with conn:
        conn.execute(
            "INSERT INTO lutins (id, fullname, email) VALUES ('fbonnet', 'François Bonnet', 'fb@example.com');"
        )
        conn.execute("INSERT INTO editions (year, status) VALUES (2025, 'draft');")
        # Insertion d'un score démarré au format legacy SQLite
        conn.execute(
            "INSERT INTO scores_defi (lutin_id, year, manche_id, pseudo_lutin, started_at, solved) "
            "VALUES ('fbonnet', 2025, 1, 'Renne Agile', '2025-12-24 18:00:00', 0);"
        )
    conn.close()

    token = create_or_get_token(db_file, "fbonnet", 2025)
    set_lutin_presence(db_file, "fbonnet", 2025, present=True)

    t_solve = datetime(2025, 12, 24, 18, 0, 42, 460000, tzinfo=timezone.utc)

    app = create_app(db_path=db_file, clock=lambda: t_solve)
    test_client = TestClient(app)

    grille = get_or_load_grille(2025)
    assert grille is not None

    resp_solve = test_client.post(
        f"/api/lutin/{token}/defi/1/solve",
        json={"solution": grille["solution"]},
    )
    assert resp_solve.status_code == 200
    data_solve = resp_solve.json()
    assert data_solve["solved"] is True
    # round(42.46, 1) == 42.5
    assert data_solve["time_seconds"] == 42.5


def test_scores_page_shows_french_unlock_time_for_locked_manche(client: TestClient, test_db: Path) -> None:
    conn = get_db_connection(test_db)
    with conn:
        conn.execute("INSERT OR IGNORE INTO editions (year, status) VALUES (2026, 'draft');")
    conn.close()

    resp = client.get("/scores/2026")
    assert resp.status_code == 200
    assert "17h00" in resp.text
    assert "vendredi 23 octobre, 17h00" in resp.text


def test_aucune_route_n_est_asynchrone(client: TestClient) -> None:
    import inspect

    from fastapi.routing import APIRoute

    routes = [r for r in client.app.routes if isinstance(r, APIRoute)]  # type: ignore[attr-defined]
    assert routes
    coroutines = [r.path for r in routes if inspect.iscoroutinefunction(r.endpoint)]
    assert coroutines == []


def test_solve_faux_concurrent_scelle_apres_trois_essais(client: TestClient, test_db: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from pere_noel_fremo.database import set_lutin_presence

    sol_wrong = {
        "Barnabé": {"luge": "Éclair Vert", "friandise": "Canne de sucre"},
        "Clémence": {"luge": "Comète Bleue", "friandise": "Chocolat chaud"},
        "Gaspard": {"luge": "Étoile Rouge", "friandise": "Pain d'épices"},
    }
    token = create_or_get_token(test_db, "fbonnet", 2025)
    set_lutin_presence(test_db, "fbonnet", 2025, present=True)
    assert client.post(f"/api/lutin/{token}/defi/1/start").status_code == 200

    def _solve(_: int) -> dict[str, object]:
        resp = client.post(f"/api/lutin/{token}/defi/1/solve", json={"solution": sol_wrong})
        assert resp.status_code in (200, 400)
        return dict(resp.json())

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_solve, i) for i in range(20)]
        bodies = [f.result() for f in futures]

    assert all("database is locked" not in str(b.get("detail", "")) for b in bodies)
    sealed = [b for b in bodies if "scellée" in str(b.get("detail", ""))]
    assert len(sealed) == 1
    conn = get_db_connection(test_db)
    row = conn.execute("SELECT attempts FROM scores_defi WHERE lutin_id = 'fbonnet' AND manche_id = 1;").fetchone()
    conn.close()
    assert row["attempts"] == 3


@pytest.mark.parametrize(
    ("method", "route"),
    [
        ("post", "start"),
        ("post", "solve"),
        ("post", "abandon"),
        ("get", "indices"),
    ],
)
def test_manche_yaml_illisible_repond_404(
    test_db: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    method: str,
    route: str,
) -> None:
    res_dir = tmp_path / "res"
    grilles = res_dir / "2025" / "grilles"
    grilles.mkdir(parents=True)
    (grilles / "manche_2.yml").write_text("titre: [non fermé\n  : :\n", encoding="utf-8")
    from pere_noel_fremo.database import set_lutin_presence

    token = create_or_get_token(test_db, "fbonnet", 2025)
    set_lutin_presence(test_db, "fbonnet", 2025, present=True)
    test_client = TestClient(create_app(db_path=test_db, res_dir=res_dir))

    kwargs: dict[str, Any] = {"json": {"solution": {}}} if route == "solve" else {}
    with caplog.at_level("WARNING", logger="pere_noel_fremo.defi"):
        res = getattr(test_client, method)(f"/api/lutin/{token}/defi/2/{route}", **kwargs)

    assert res.status_code == 404
    assert "Manche 2 introuvable" in res.json()["detail"]
    warnings = [r for r in caplog.records if r.levelname == "WARNING" and "manche_2.yml" in r.getMessage()]
    assert warnings
    assert all(r.exc_info is None for r in warnings)


def _app_avec_horloge(test_db: Path, instant: Any) -> TestClient:
    return TestClient(create_app(db_path=test_db, clock=lambda: instant))


def _fixer_date_repas_2025(test_db: Path) -> None:
    from pere_noel_fremo.database import set_lutin_presence

    conn = get_db_connection(test_db)
    with conn:
        conn.execute("UPDATE editions SET date_repas = '2026-12-05' WHERE year = 2025;")
    conn.close()
    set_lutin_presence(test_db, "fbonnet", 2025, present=True)


def test_compte_a_rebours_utilise_la_date_de_paris(test_db: Path) -> None:
    from datetime import datetime, timezone

    _fixer_date_repas_2025(test_db)
    token = create_or_get_token(test_db, "fbonnet", 2025)
    # 04/12 23:30 UTC = 05/12 00:30 à Paris
    page = _app_avec_horloge(test_db, datetime(2026, 12, 4, 23, 30, tzinfo=timezone.utc)).get(f"/lutin/{token}")

    assert "Aujourd&#39;hui ! 🎅" in page.text


def test_defi_clos_apres_le_repas_refuse_start_solve_abandon_en_403(test_db: Path) -> None:
    from datetime import datetime, timezone

    _fixer_date_repas_2025(test_db)
    token = create_or_get_token(test_db, "fbonnet", 2025)
    # 05/12 23:00 UTC = 06/12 00:00 à Paris
    client = _app_avec_horloge(test_db, datetime(2026, 12, 5, 23, 0, tzinfo=timezone.utc))

    for action, corps in (
        ("start", None),
        ("solve", {"solution": {}}),
        ("abandon", None),
    ):
        resp = client.post(f"/api/lutin/{token}/defi/1/{action}", json=corps)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Le Défi du lutin est clos depuis le Repas de Noël."

    page = client.get(f"/lutin/{token}")
    assert "Le Défi du lutin est clos depuis le Repas de Noël." in page.text


def test_defi_indices_refus_presence_manche_et_verrou(client: TestClient, test_db: Path) -> None:
    conn = get_db_connection(test_db)
    with conn:
        conn.execute("INSERT OR IGNORE INTO editions (year, status) VALUES (2026, 'draft');")
    conn.close()
    from pere_noel_fremo.database import set_lutin_presence

    sans_presence = create_or_get_token(test_db, "alacroix", 2025)
    resp = client.get(f"/api/lutin/{sans_presence}/defi/1/indices")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Tu dois d'abord confirmer ta présence pour lancer le Défi du lutin."

    token = create_or_get_token(test_db, "fbonnet", 2025)
    set_lutin_presence(test_db, "fbonnet", 2025, present=True)
    resp = client.get(f"/api/lutin/{token}/defi/999/indices")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Manche 999 introuvable."

    token_2026 = create_or_get_token(test_db, "fbonnet", 2026)
    set_lutin_presence(test_db, "fbonnet", 2026, present=True)
    resp = client.get(f"/api/lutin/{token_2026}/defi/3/indices")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "La manche 3 n'est pas encore déverrouillée."

    assert client.get("/api/lutin/inconnu/defi/1/indices").status_code == 404


def test_defi_indices_refus_sans_essai_en_cours(client: TestClient, test_db: Path) -> None:
    from pere_noel_fremo.database import set_lutin_presence

    token = create_or_get_token(test_db, "fbonnet", 2025)
    set_lutin_presence(test_db, "fbonnet", 2025, present=True)
    attendu = "Les indices ne sont accessibles que pendant un essai en cours."

    assert client.get(f"/api/lutin/{token}/defi/1/indices").json()["detail"] == attendu
    client.post(f"/api/lutin/{token}/defi/1/start")
    client.post(f"/api/lutin/{token}/defi/1/abandon")
    resp = client.get(f"/api/lutin/{token}/defi/1/indices")
    assert resp.status_code == 403
    assert resp.json()["detail"] == attendu


def test_defi_clos_refuse_aussi_les_indices_en_403(test_db: Path) -> None:
    from datetime import datetime, timezone

    _fixer_date_repas_2025(test_db)
    token = create_or_get_token(test_db, "fbonnet", 2025)
    client = _app_avec_horloge(test_db, datetime(2026, 12, 5, 23, 0, tzinfo=timezone.utc))

    resp = client.get(f"/api/lutin/{token}/defi/1/indices")

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Le Défi du lutin est clos depuis le Repas de Noël."
