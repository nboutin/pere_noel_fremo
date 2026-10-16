from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pere_noel_fremo.database import (
    get_db_connection,
    get_lutin_presence,
    init_db,
    register_solve_attempt,
    set_lutin_presence,
)
from pere_noel_fremo.parcours import StatutParcours, abandonner, demarrer

NOW = datetime(2026, 10, 14, 20, 0, 0, tzinfo=timezone.utc)
YEAR = 2026


def _manche(**overrides: Any) -> dict[str, Any]:
    manche: dict[str, Any] = {
        "id": 1,
        "unlock_at": "2026-10-12 19:00:00",
        "categories": {
            "lutins": ["Barnabé", "Clémence"],
            "luges": ["Étoile Rouge", "Comète Bleue"],
        },
        "attributs": {"luge": "luges"},
        "indices": ["Indice un.", "Indice deux."],
        "solution": {
            "Barnabé": {"luge": "Comète Bleue"},
            "Clémence": {"luge": "Étoile Rouge"},
        },
    }
    manche.update(overrides)
    return manche


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "parcours.db"
    init_db(path)
    conn = get_db_connection(path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname) VALUES ('l1', 'Lutin 1');")
    conn.close()
    return path


@pytest.fixture
def present(db_path: Path) -> Path:
    set_lutin_presence(db_path, "l1", YEAR, True)
    return db_path


def _count(db_path: Path, table: str) -> int:
    conn = get_db_connection(db_path)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0])  # noqa: S608
    finally:
        conn.close()


def test_demarrer_sans_presence_ne_cree_rien(db_path: Path) -> None:
    res = demarrer(db_path, "l1", YEAR, _manche(), NOW)

    assert res.statut is StatutParcours.PRESENCE_REQUISE
    assert _count(db_path, "pseudos") == 0
    assert _count(db_path, "scores_defi") == 0


def test_demarrer_avec_presence_refusee_est_presence_requise(db_path: Path) -> None:
    set_lutin_presence(db_path, "l1", YEAR, False)

    assert demarrer(db_path, "l1", YEAR, _manche(), NOW).statut is StatutParcours.PRESENCE_REQUISE


def test_demarrer_manche_inexistante_apres_controle_de_presence(present: Path, db_path: Path) -> None:
    assert demarrer(present, "l1", YEAR, None, NOW).statut is StatutParcours.MANCHE_INTROUVABLE
    set_lutin_presence(db_path, "l1", YEAR, False)
    assert demarrer(present, "l1", YEAR, None, NOW).statut is StatutParcours.PRESENCE_REQUISE


def test_demarrer_manche_verrouillee(present: Path) -> None:
    manche = _manche(unlock_at="2026-10-20 19:00:00")

    res = demarrer(present, "l1", YEAR, manche, NOW)

    assert res.statut is StatutParcours.MANCHE_VERROUILLEE
    assert _count(present, "pseudos") == 0
    assert _count(present, "scores_defi") == 0


def test_demarrer_grille_invalide(present: Path) -> None:
    res = demarrer(present, "l1", YEAR, _manche(solution={}), NOW)

    assert res.statut is StatutParcours.GRILLE_INVALIDE
    assert res.detail
    assert _count(present, "pseudos") == 0
    assert _count(present, "scores_defi") == 0


def test_demarrer_nominal_cree_pseudo_et_score(present: Path) -> None:
    res = demarrer(present, "l1", YEAR, _manche(), NOW)

    assert res.statut is StatutParcours.DEMARRE
    assert res.pseudo_lutin
    assert res.started_at == NOW.isoformat()
    assert res.indices == ["Indice un.", "Indice deux."]
    conn = get_db_connection(present)
    row = conn.execute("SELECT pseudo_lutin, started_at, solved FROM scores_defi;").fetchone()
    pseudo = conn.execute("SELECT pseudo FROM pseudos WHERE lutin_id = 'l1';").fetchone()["pseudo"]
    conn.close()
    assert row["pseudo_lutin"] == pseudo == res.pseudo_lutin
    assert row["started_at"] == NOW.isoformat()
    assert row["solved"] == 0


def test_demarrer_deux_fois_conserve_l_heure_de_depart(present: Path) -> None:
    first = demarrer(present, "l1", YEAR, _manche(), NOW)
    second = demarrer(present, "l1", YEAR, _manche(), NOW + timedelta(minutes=5))

    assert second.statut is StatutParcours.DEMARRE
    assert second.started_at == first.started_at
    assert _count(present, "scores_defi") == 1


def test_demarrer_manche_resolue(present: Path) -> None:
    demarrer(present, "l1", YEAR, _manche(), NOW)
    register_solve_attempt(present, "l1", YEAR, 1, is_valid=True, now=NOW + timedelta(seconds=30))

    assert demarrer(present, "l1", YEAR, _manche(), NOW).statut is StatutParcours.DEJA_RESOLUE


def test_demarrer_manche_abandonnee(present: Path) -> None:
    demarrer(present, "l1", YEAR, _manche(), NOW)
    abandonner(present, "l1", YEAR, _manche(), NOW + timedelta(seconds=10))

    assert demarrer(present, "l1", YEAR, _manche(), NOW).statut is StatutParcours.DEJA_TERMINEE


def test_abandonner_nominal(present: Path) -> None:
    started = demarrer(present, "l1", YEAR, _manche(), NOW)
    later = NOW + timedelta(seconds=10)

    res = abandonner(present, "l1", YEAR, _manche(), later)

    assert res.statut is StatutParcours.ABANDONNE
    assert res.pseudo_lutin == started.pseudo_lutin
    conn = get_db_connection(present)
    row = conn.execute("SELECT solved, time_seconds, completed_at FROM scores_defi;").fetchone()
    conn.close()
    assert row["solved"] == 0
    assert row["time_seconds"] is None
    assert row["completed_at"] == later.isoformat()


def test_abandonner_manche_non_demarree(present: Path) -> None:
    res = abandonner(present, "l1", YEAR, _manche(), NOW)

    assert res.statut is StatutParcours.NON_DEMARRE
    assert _count(present, "scores_defi") == 0


def test_abandonner_deux_fois(present: Path) -> None:
    demarrer(present, "l1", YEAR, _manche(), NOW)
    abandonner(present, "l1", YEAR, _manche(), NOW)

    assert abandonner(present, "l1", YEAR, _manche(), NOW).statut is StatutParcours.DEJA_TERMINEE


def test_abandonner_sans_presence(db_path: Path) -> None:
    assert get_lutin_presence(db_path, "l1", YEAR) is None
    assert abandonner(db_path, "l1", YEAR, _manche(), NOW).statut is StatutParcours.PRESENCE_REQUISE


def test_abandonner_manche_verrouillee(present: Path) -> None:
    res = abandonner(present, "l1", YEAR, _manche(unlock_at="2026-10-20 19:00:00"), NOW)

    assert res.statut is StatutParcours.MANCHE_VERROUILLEE
