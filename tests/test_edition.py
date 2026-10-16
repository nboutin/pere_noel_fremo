import itertools
from datetime import date
from pathlib import Path

import pytest
from pere_noel_fremo.database import get_db_connection, init_db
from pere_noel_fremo.edition import (
    StatutEdition,
    TransitionEditionInterdite,
    annee_courante,
    avancer,
    est_scellee,
    statut,
)

PERMISES = {
    (StatutEdition.DRAFT, StatutEdition.ANNOUNCED),
    (StatutEdition.ANNOUNCED, StatutEdition.DRAWN),
    (StatutEdition.DRAWN, StatutEdition.REVEALED),
    (StatutEdition.DRAWN, StatutEdition.DRAWN),
}


def _forcer_statut(db_path: Path, year: int, valeur: str) -> None:
    conn = get_db_connection(db_path)
    with conn:
        conn.execute(
            "INSERT INTO editions (year, status) VALUES (?, ?) ON CONFLICT(year) DO UPDATE SET status=excluded.status;",
            (year, valeur),
        )
    conn.close()


def test_statut_enum_a_quatre_valeurs() -> None:
    assert [s.value for s in StatutEdition] == ["draft", "announced", "drawn", "revealed"]


@pytest.mark.parametrize(
    ("statut_edition", "attendu"),
    [
        (StatutEdition.DRAFT, False),
        (StatutEdition.ANNOUNCED, False),
        (StatutEdition.DRAWN, True),
        (StatutEdition.REVEALED, True),
    ],
)
def test_est_scellee(statut_edition: StatutEdition, attendu: bool) -> None:
    assert est_scellee(statut_edition) is attendu


def test_statut_edition_absente_vaut_draft(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    assert statut(db_path, 2026) is StatutEdition.DRAFT


@pytest.mark.parametrize(("de", "vers"), list(itertools.product(StatutEdition, StatutEdition)))
def test_avancer_toutes_les_transitions(tmp_path: Path, de: StatutEdition, vers: StatutEdition) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    _forcer_statut(db_path, 2026, de.value)
    conn = get_db_connection(db_path)
    try:
        if (de, vers) in PERMISES:
            avancer(conn, 2026, vers)
            conn.commit()
            assert statut(conn, 2026) is vers
        else:
            with pytest.raises(TransitionEditionInterdite):
                avancer(conn, 2026, vers)
            assert statut(conn, 2026) is de
    finally:
        conn.close()


def test_avancer_cree_l_edition_absente_depuis_draft(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    conn = get_db_connection(db_path)
    try:
        avancer(conn, 2031, StatutEdition.ANNOUNCED)
        conn.commit()
        assert statut(conn, 2031) is StatutEdition.ANNOUNCED
    finally:
        conn.close()


def test_avancer_participe_a_la_transaction_de_l_appelant(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    _forcer_statut(db_path, 2026, "announced")
    conn = get_db_connection(db_path)
    try:
        avancer(conn, 2026, StatutEdition.DRAWN)
        conn.rollback()
    finally:
        conn.close()
    assert statut(db_path, 2026) is StatutEdition.ANNOUNCED


def test_annee_courante_prend_la_plus_recente(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    _forcer_statut(db_path, 2024, "draft")
    _forcer_statut(db_path, 2027, "draft")
    assert annee_courante(db_path) == 2027


def test_annee_courante_base_vide_utilise_l_horloge(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    assert annee_courante(db_path) == date.today().year


def test_annee_courante_base_inexistante_ne_cree_pas_de_fichier(tmp_path: Path) -> None:
    db_path = tmp_path / "absente.db"
    assert annee_courante(db_path) == date.today().year
    assert not db_path.exists()
