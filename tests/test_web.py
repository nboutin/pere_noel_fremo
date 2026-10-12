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

    # La page HTML contient maintenant la carte à gratter et le nom sous le canvas
    page_after_draw = client.get(f"/lutin/{token}")
    assert page_after_draw.status_code == 200
    assert "Alice Lacroix" in page_after_draw.text
