"""Grilles pilotées par les catégories de chaque manche (spec #36, ticket #37)."""

import html
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml
from pere_noel_fremo.database import get_db_connection, init_db, set_lutin_presence
from pere_noel_fremo.defi import (
    GrilleInvalideError,
    get_manche_attributes,
    is_solution_complete,
    validate_grille_solution,
)
from pere_noel_fremo.tokens import create_or_get_token
from pere_noel_fremo.web import create_app
from starlette.testclient import TestClient

RES_DIR = Path(__file__).resolve().parent.parent / "res"
GRILLES = sorted((RES_DIR / "2026" / "grilles").glob("manche_*.yml"))
APRES_DERNIER_UNLOCK = datetime(2026, 12, 31, 12, 0, 0, tzinfo=timezone.utc)


def _load(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict)
    return data


def test_quinze_grilles_presentes() -> None:
    assert len(GRILLES) == 15


@pytest.mark.parametrize("path", GRILLES, ids=lambda p: p.stem)
def test_grille_coherente(path: Path) -> None:
    grille = _load(path)
    categories = grille["categories"]
    solution = grille["solution"]

    assert sorted(categories["lutins"]) == sorted(solution.keys())

    attributes = get_manche_attributes(grille)
    assert len(attributes) >= 1
    for key, categorie in attributes:
        assert sorted(entry[key] for entry in solution.values()) == sorted(categories[categorie])


def test_attributes_explicites_ordonnes() -> None:
    grille = _load(RES_DIR / "2026" / "grilles" / "manche_2.yml")
    assert get_manche_attributes(grille) == [("bonnet", "bonnets"), ("cadeau", "cadeaux")]


def test_attributes_derives_sans_champ_explicite() -> None:
    grille = {
        "categories": {"lutins": ["A", "B"], "luges": ["x", "y"], "friandises": ["p", "q"]},
        "solution": {"A": {"luge": "x", "friandise": "p"}, "B": {"luge": "y", "friandise": "q"}},
    }
    assert get_manche_attributes(grille) == [("luge", "luges"), ("friandise", "friandises")]


def test_attributes_derives_pluriel_en_x() -> None:
    grille = {
        "categories": {"lutins": ["A", "B"], "cadeaux": ["x", "y"]},
        "solution": {"A": {"cadeau": "x"}, "B": {"cadeau": "y"}},
    }
    assert get_manche_attributes(grille) == [("cadeau", "cadeaux")]


def test_attributes_cle_absente_des_categories() -> None:
    grille = {
        "categories": {"lutins": ["A", "B"], "luges": ["x", "y"]},
        "solution": {"A": {"traineau": "x"}, "B": {"traineau": "y"}},
    }
    with pytest.raises(GrilleInvalideError):
        get_manche_attributes(grille)


def test_attributes_valeur_hors_categorie() -> None:
    grille = {
        "categories": {"lutins": ["A", "B"], "luges": ["x", "y"]},
        "solution": {"A": {"luge": "x"}, "B": {"luge": "z"}},
    }
    with pytest.raises(GrilleInvalideError):
        get_manche_attributes(grille)


def test_attributes_pas_une_permutation() -> None:
    grille = {
        "categories": {"lutins": ["A", "B"], "luges": ["x", "y"]},
        "solution": {"A": {"luge": "x"}, "B": {"luge": "x"}},
    }
    with pytest.raises(GrilleInvalideError):
        get_manche_attributes(grille)


def test_attributes_lutins_incoherents_avec_solution() -> None:
    grille = {
        "categories": {"lutins": ["A", "C"], "luges": ["x", "y"]},
        "solution": {"A": {"luge": "x"}, "B": {"luge": "y"}},
    }
    with pytest.raises(GrilleInvalideError):
        get_manche_attributes(grille)


def test_attributes_explicites_vers_categorie_inconnue() -> None:
    grille = {
        "attributs": {"luge": "traineaux"},
        "categories": {"lutins": ["A"], "luges": ["x"]},
        "solution": {"A": {"luge": "x"}},
    }
    with pytest.raises(GrilleInvalideError):
        get_manche_attributes(grille)


def test_attributes_derivation_ambigue() -> None:
    grille = {
        "categories": {"lutins": ["A"], "cadeaus": ["x"], "cadeaux": ["x"]},
        "solution": {"A": {"cadeau": "x"}},
    }
    with pytest.raises(GrilleInvalideError):
        get_manche_attributes(grille)


@pytest.mark.parametrize("path", GRILLES, ids=lambda p: p.stem)
def test_solution_yaml_est_complete_et_valide(path: Path) -> None:
    grille = _load(path)
    assert is_solution_complete(grille, grille["solution"]) is True
    assert validate_grille_solution(grille, grille["solution"]) is True


def test_solution_incomplete_sur_attribut_non_luge() -> None:
    grille = _load(RES_DIR / "2026" / "grilles" / "manche_2.yml")
    partielle = {name: {"bonnet": entry["bonnet"]} for name, entry in grille["solution"].items()}
    assert is_solution_complete(grille, partielle) is False
    luge_friandise: dict[str, Any] = {name: {"luge": "a", "friandise": "b"} for name in grille["solution"]}
    assert is_solution_complete(grille, luge_friandise) is False


def test_grille_invalide_jamais_complete() -> None:
    grille: dict[str, Any] = {
        "categories": {"lutins": ["A"], "luges": ["x"]},
        "solution": {"A": {"traineau": "x"}},
    }
    assert is_solution_complete(grille, grille["solution"]) is False


@pytest.fixture
def web_env(tmp_path: Path) -> tuple[Path, TestClient]:
    db_file = tmp_path / "grilles.db"
    init_db(db_file)
    conn = get_db_connection(db_file)
    with conn:
        conn.execute(
            "INSERT INTO lutins (id, fullname, email) VALUES ('fbonnet', 'François Bonnet', 'fb@example.com');"
        )
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
    conn.close()
    app = create_app(db_path=db_file, res_dir=RES_DIR, clock=lambda: APRES_DERNIER_UNLOCK)
    return db_file, TestClient(app)


@pytest.mark.parametrize("path", GRILLES, ids=lambda p: p.stem)
def test_manche_jouable_de_bout_en_bout(path: Path, web_env: tuple[Path, TestClient]) -> None:
    db_file, client = web_env
    grille = _load(path)
    manche_id = int(grille["id"])
    token = create_or_get_token(db_file, "fbonnet", 2026)
    set_lutin_presence(db_file, "fbonnet", 2026, present=True)

    page = client.get(f"/lutin/{token}?manche={manche_id}")
    assert page.status_code == 200
    rendered = html.unescape(page.text)
    for key, categorie in get_manche_attributes(grille):
        for option in grille["categories"][categorie]:
            assert f'<option value="{option}">' in rendered, (key, option)
        for lutin in grille["categories"]["lutins"]:
            assert f'id="select-{key}-{lutin}"' in rendered

    start = client.post(f"/api/lutin/{token}/defi/{manche_id}/start")
    assert start.status_code == 200

    solve = client.post(f"/api/lutin/{token}/defi/{manche_id}/solve", json={"solution": grille["solution"]})
    assert solve.status_code == 200
    body = solve.json()
    assert body["solved"] is True
    assert body["attempts"] == 1


def test_start_refuse_manche_incoherente(tmp_path: Path) -> None:
    res_dir = tmp_path / "res"
    grilles_dir = res_dir / "2026" / "grilles"
    grilles_dir.mkdir(parents=True)
    (grilles_dir / "manche_1.yml").write_text(
        yaml.safe_dump(
            {
                "id": 1,
                "title": "Cassée",
                "unlock_at": "2026-10-12 19:00:00",
                "categories": {"lutins": ["A", "B"], "luges": ["x", "y"]},
                "indices": ["rien"],
                "solution": {"A": {"traineau": "x"}, "B": {"traineau": "y"}},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    db_file = tmp_path / "cassee.db"
    init_db(db_file)
    conn = get_db_connection(db_file)
    with conn:
        conn.execute(
            "INSERT INTO lutins (id, fullname, email) VALUES ('fbonnet', 'François Bonnet', 'fb@example.com');"
        )
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
    conn.close()
    token = create_or_get_token(db_file, "fbonnet", 2026)
    set_lutin_presence(db_file, "fbonnet", 2026, present=True)

    client = TestClient(create_app(db_path=db_file, res_dir=res_dir, clock=lambda: APRES_DERNIER_UNLOCK))
    resp = client.post(f"/api/lutin/{token}/defi/1/start")
    assert resp.status_code == 409

    conn = sqlite3.connect(db_file)
    try:
        assert conn.execute("SELECT COUNT(*) FROM scores_defi").fetchone()[0] == 0
    finally:
        conn.close()
