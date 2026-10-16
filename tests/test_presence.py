from pathlib import Path

import pytest
from pere_noel_fremo.database import get_db_connection, get_lutin_presence, init_db, set_edition_status
from pere_noel_fremo.presence import StatutPresence, confirmer

YEAR = 2026


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "presence.db"
    init_db(path)
    conn = get_db_connection(path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'announced');")
        conn.execute("INSERT INTO lutins (id, fullname) VALUES ('l1', 'Lutin 1');")
    conn.close()
    return path


def test_confirmer_enregistre_la_presence(db_path: Path) -> None:
    assert confirmer(db_path, "l1", YEAR, True) is StatutPresence.ENREGISTREE
    assert get_lutin_presence(db_path, "l1", YEAR) is True
    assert confirmer(db_path, "l1", YEAR, False) is StatutPresence.ENREGISTREE
    assert get_lutin_presence(db_path, "l1", YEAR) is False


@pytest.mark.parametrize("statut", ["drawn", "revealed"])
def test_confirmer_refuse_une_edition_scellee_sans_rien_ecrire(db_path: Path, statut: str) -> None:
    assert confirmer(db_path, "l1", YEAR, True) is StatutPresence.ENREGISTREE
    # Le scellement survient entre la lecture du jeton et la confirmation : la garde relit le statut
    # dans la transaction d'écriture.
    set_edition_status(db_path, YEAR, statut)

    assert confirmer(db_path, "l1", YEAR, False) is StatutPresence.VERROUILLEE
    assert get_lutin_presence(db_path, "l1", YEAR) is True


def test_confirmer_refuse_sans_creer_de_ligne(db_path: Path) -> None:
    set_edition_status(db_path, YEAR, "drawn")

    assert confirmer(db_path, "l1", YEAR, True) is StatutPresence.VERROUILLEE
    assert get_lutin_presence(db_path, "l1", YEAR) is None
