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
