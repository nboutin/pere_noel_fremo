import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pere_noel_fremo.database import (
    get_db_connection,
    get_lutin_presence,
    init_db,
    set_lutin_presence,
)
from pere_noel_fremo.defi import MAX_ESSAIS_PAR_MANCHE, PENALITE_ESSAI_FAUX_SECONDES
from pere_noel_fremo.parcours import (
    StatutManche,
    StatutParcours,
    StatutSoumission,
    abandonner,
    demarrer,
    etat,
    soumettre,
)

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
    soumettre(present, "l1", YEAR, _manche(), _manche()["solution"], NOW + timedelta(seconds=30))

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


# --- Soumission ---------------------------------------------------------------------------------

JUSTE = _manche()["solution"]
FAUSSE = {
    "Barnabé": {"luge": "Étoile Rouge"},
    "Clémence": {"luge": "Comète Bleue"},
}
INCOMPLETE = {"Barnabé": {"luge": "Comète Bleue"}}


def _score(db_path: Path) -> Any:
    conn = get_db_connection(db_path)
    try:
        return conn.execute("SELECT * FROM scores_defi;").fetchone()
    finally:
        conn.close()


@pytest.fixture
def demarree(present: Path) -> Path:
    demarrer(present, "l1", YEAR, _manche(), NOW)
    return present


def test_soumettre_reussite_au_premier_essai_sans_penalite(demarree: Path) -> None:
    res = soumettre(demarree, "l1", YEAR, _manche(), JUSTE, NOW + timedelta(seconds=42.5))

    assert res.statut is StatutSoumission.RESOLUE
    assert res.attempts == 1
    assert res.essais_restants == MAX_ESSAIS_PAR_MANCHE - 1
    assert res.penalite_cumulee_secondes == 0
    assert res.time_seconds == 42.5
    assert res.pseudo_lutin
    row = _score(demarree)
    assert (row["solved"], row["attempts"], row["time_seconds"]) == (1, 1, 42.5)
    assert row["completed_at"] == (NOW + timedelta(seconds=42.5)).isoformat()


def test_soumettre_reussite_au_troisieme_essai_ajoute_trente_secondes(demarree: Path) -> None:
    for i in (10, 20):
        faux = soumettre(demarree, "l1", YEAR, _manche(), FAUSSE, NOW + timedelta(seconds=i))
        assert faux.statut is StatutSoumission.FAUSSE

    res = soumettre(demarree, "l1", YEAR, _manche(), JUSTE, NOW + timedelta(seconds=60))

    assert res.statut is StatutSoumission.RESOLUE
    assert res.attempts == 3
    assert res.penalite_cumulee_secondes == 2 * PENALITE_ESSAI_FAUX_SECONDES == 30
    assert res.time_seconds == 90.0
    assert _score(demarree)["time_seconds"] == 90.0


def test_soumettre_fausse_decompte_les_essais_restants(demarree: Path) -> None:
    res = soumettre(demarree, "l1", YEAR, _manche(), FAUSSE, NOW + timedelta(seconds=10))

    assert res.statut is StatutSoumission.FAUSSE
    assert res.attempts == 1
    assert res.essais_restants == 2
    assert res.essais_max == MAX_ESSAIS_PAR_MANCHE
    assert res.penalite_essai_secondes == PENALITE_ESSAI_FAUX_SECONDES
    assert res.penalite_cumulee_secondes == PENALITE_ESSAI_FAUX_SECONDES
    assert res.time_seconds is None
    row = _score(demarree)
    assert (row["attempts"], row["solved"], row["completed_at"]) == (1, 0, None)


def test_soumettre_trois_fausses_scelle_la_manche(demarree: Path) -> None:
    resultats = [soumettre(demarree, "l1", YEAR, _manche(), FAUSSE, NOW + timedelta(seconds=i)) for i in (10, 20, 30)]

    assert [r.statut for r in resultats] == [
        StatutSoumission.FAUSSE,
        StatutSoumission.FAUSSE,
        StatutSoumission.SCELLEE,
    ]
    assert resultats[2].attempts == 3
    assert resultats[2].essais_restants == 0
    row = _score(demarree)
    assert (row["solved"], row["time_seconds"], row["attempts"]) == (0, None, 3)
    assert row["completed_at"] == (NOW + timedelta(seconds=30)).isoformat()


def test_soumettre_incomplete_ne_consomme_pas_d_essai(demarree: Path) -> None:
    res = soumettre(demarree, "l1", YEAR, _manche(), INCOMPLETE, NOW + timedelta(seconds=5))

    assert res.statut is StatutSoumission.INCOMPLETE
    assert res.attempts == 0
    assert res.essais_restants == MAX_ESSAIS_PAR_MANCHE
    assert _score(demarree)["attempts"] == 0


def test_soumettre_sur_manche_scellee_est_deja_terminee(demarree: Path) -> None:
    for i in (10, 20, 30):
        soumettre(demarree, "l1", YEAR, _manche(), FAUSSE, NOW + timedelta(seconds=i))

    res = soumettre(demarree, "l1", YEAR, _manche(), JUSTE, NOW + timedelta(seconds=40))

    assert res.statut is StatutSoumission.DEJA_TERMINEE
    assert res.attempts == 3
    row = _score(demarree)
    assert (row["solved"], row["attempts"]) == (0, 3)


def test_soumettre_sur_manche_resolue_ne_modifie_pas_le_temps(demarree: Path) -> None:
    soumettre(demarree, "l1", YEAR, _manche(), JUSTE, NOW + timedelta(seconds=42.5))

    res = soumettre(demarree, "l1", YEAR, _manche(), JUSTE, NOW + timedelta(seconds=999))

    assert res.statut is StatutSoumission.DEJA_TERMINEE
    assert _score(demarree)["time_seconds"] == 42.5


def test_soumettre_sur_manche_abandonnee_est_deja_terminee(demarree: Path) -> None:
    abandonner(demarree, "l1", YEAR, _manche(), NOW + timedelta(seconds=5))

    res = soumettre(demarree, "l1", YEAR, _manche(), JUSTE, NOW + timedelta(seconds=10))

    assert res.statut is StatutSoumission.DEJA_TERMINEE
    assert _score(demarree)["solved"] == 0


def test_soumettre_sans_demarrage(present: Path) -> None:
    res = soumettre(present, "l1", YEAR, _manche(), JUSTE, NOW)

    assert res.statut is StatutSoumission.NON_DEMARRE
    assert _count(present, "scores_defi") == 0


def test_soumettre_non_demarre_prime_sur_incomplete(present: Path) -> None:
    assert soumettre(present, "l1", YEAR, _manche(), INCOMPLETE, NOW).statut is StatutSoumission.NON_DEMARRE


def test_soumettre_gardes_presence_existence_et_verrouillage(db_path: Path, present: Path) -> None:
    assert soumettre(present, "l1", YEAR, None, JUSTE, NOW).statut is StatutSoumission.MANCHE_INTROUVABLE
    verrouillee = _manche(unlock_at="2026-10-20 19:00:00")
    assert soumettre(present, "l1", YEAR, verrouillee, JUSTE, NOW).statut is StatutSoumission.MANCHE_VERROUILLEE
    set_lutin_presence(db_path, "l1", YEAR, False)
    assert soumettre(present, "l1", YEAR, _manche(), JUSTE, NOW).statut is StatutSoumission.PRESENCE_REQUISE
    assert _count(present, "scores_defi") == 0


def test_soumettre_concurrente_fausses_plafonne_a_trois_essais(demarree: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(soumettre, demarree, "l1", YEAR, _manche(), FAUSSE, NOW) for _ in range(20)]
        statuts = [f.result().statut for f in futures]

    row = _score(demarree)
    assert row["attempts"] == 3
    assert row["completed_at"] is not None
    assert statuts.count(StatutSoumission.SCELLEE) == 1
    assert statuts.count(StatutSoumission.FAUSSE) == 2
    assert statuts.count(StatutSoumission.DEJA_TERMINEE) == 17


def test_soumission_juste_et_abandon_concurrents_un_seul_gagnant(demarree: Path) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    barrier = threading.Barrier(2)

    def resoudre() -> StatutSoumission:
        barrier.wait()
        return soumettre(demarree, "l1", YEAR, _manche(), JUSTE, NOW + timedelta(seconds=30)).statut

    def abandon() -> StatutParcours:
        barrier.wait()
        return abandonner(demarree, "l1", YEAR, _manche(), NOW + timedelta(seconds=30)).statut

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_solve = pool.submit(resoudre)
        f_abandon = pool.submit(abandon)
        statut_solve, statut_abandon = f_solve.result(), f_abandon.result()

    row = _score(demarree)
    assert row["completed_at"] is not None
    if row["solved"]:
        assert statut_solve is StatutSoumission.RESOLUE
        assert statut_abandon is StatutParcours.DEJA_TERMINEE
        assert row["time_seconds"] == 30.0
    else:
        assert statut_solve is StatutSoumission.DEJA_TERMINEE
        assert statut_abandon is StatutParcours.ABANDONNE
        assert row["time_seconds"] is None


def _inserer_score(
    db_path: Path,
    manche_id: int,
    *,
    solved: int = 0,
    attempts: int = 0,
    time_seconds: float | None = None,
    completed: bool = False,
) -> None:
    conn = get_db_connection(db_path)
    with conn:
        conn.execute(
            "INSERT INTO scores_defi (lutin_id, year, manche_id, pseudo_lutin, started_at, solved, attempts, "
            "time_seconds, completed_at) VALUES ('l1', ?, ?, 'Lutin Test', ?, ?, ?, ?, ?);",
            (YEAR, manche_id, NOW.isoformat(), solved, attempts, time_seconds, NOW.isoformat() if completed else None),
        )
    conn.close()


def test_etat_une_manche_dans_chaque_statut_en_une_seule_requete(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pere_noel_fremo import parcours

    _inserer_score(db_path, 1, solved=1, attempts=2, time_seconds=42.5, completed=True)
    _inserer_score(db_path, 2, attempts=1, completed=True)
    _inserer_score(db_path, 3, attempts=MAX_ESSAIS_PAR_MANCHE, completed=True)
    _inserer_score(db_path, 5, attempts=1)
    manches = [
        _manche(id=1),
        _manche(id=2),
        _manche(id=3),
        _manche(id=4),
        _manche(id=5),
        _manche(id=6, unlock_at="2099-01-01 00:00:00"),
    ]
    requetes: list[str] = []
    ouvrir = parcours.get_db_connection

    def _connexion_tracee(path: Path | str) -> sqlite3.Connection:
        conn = ouvrir(path)
        conn.set_trace_callback(requetes.append)
        return conn

    monkeypatch.setattr(parcours, "get_db_connection", _connexion_tracee)

    etats = etat(db_path, "l1", YEAR, manches, NOW)

    assert [e.statut for e in etats] == [
        StatutManche.RESOLUE,
        StatutManche.ABANDONNEE,
        StatutManche.SCELLEE,
        StatutManche.DISPONIBLE,
        StatutManche.EN_COURS,
        StatutManche.VERROUILLEE,
    ]
    assert [e.manche_id for e in etats] == [1, 2, 3, 4, 5, 6]
    assert (etats[0].attempts, etats[0].time_seconds, etats[0].pseudo_lutin) == (2, 42.5, "Lutin Test")
    assert etats[2].attempts == MAX_ESSAIS_PAR_MANCHE
    assert etats[4].started_at == NOW.isoformat()
    assert etats[3].started_at is None
    assert (etats[3].attempts, etats[3].time_seconds, etats[3].pseudo_lutin) == (0, None, None)
    assert len([r for r in requetes if "FROM scores_defi" in r]) == 1


# --- Clôture du Défi après le Repas de Noël (ADR-0007 §2) ---

PARIS = ZoneInfo("Europe/Paris")
DERNIERE_MINUTE = datetime(2026, 12, 5, 23, 59, tzinfo=PARIS)
PREMIERE_MINUTE = datetime(2026, 12, 6, 0, 0, tzinfo=PARIS)


def _fixer_date_repas(db_path: Path, date_repas: str | None) -> None:
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("UPDATE editions SET date_repas = ? WHERE year = ?;", (date_repas, YEAR))
    conn.close()


def test_defi_ouvert_jusqu_a_la_fin_du_jour_du_repas(present: Path) -> None:
    _fixer_date_repas(present, "2026-12-05")

    assert demarrer(present, "l1", YEAR, _manche(), DERNIERE_MINUTE).statut is StatutParcours.DEMARRE
    assert soumettre(present, "l1", YEAR, _manche(), FAUSSE, DERNIERE_MINUTE).statut is StatutSoumission.FAUSSE
    assert abandonner(present, "l1", YEAR, _manche(), DERNIERE_MINUTE).statut is StatutParcours.ABANDONNE


def test_defi_clos_des_minuit_heure_de_paris(present: Path) -> None:
    _fixer_date_repas(present, "2026-12-05")

    assert demarrer(present, "l1", YEAR, _manche(), PREMIERE_MINUTE).statut is StatutParcours.DEFI_CLOS
    assert soumettre(present, "l1", YEAR, _manche(), JUSTE, PREMIERE_MINUTE).statut is StatutSoumission.DEFI_CLOS
    assert abandonner(present, "l1", YEAR, _manche(), PREMIERE_MINUTE).statut is StatutParcours.DEFI_CLOS
    assert _count(present, "scores_defi") == 0


def test_defi_clos_compare_en_heure_de_paris_pas_en_utc(present: Path) -> None:
    _fixer_date_repas(present, "2026-12-05")
    # 05/12 23:30 UTC = 06/12 00:30 Paris : clos ; 05/12 22:30 UTC = 23:30 Paris : ouvert
    assert demarrer(present, "l1", YEAR, _manche(), datetime(2026, 12, 5, 23, 30, tzinfo=timezone.utc)).statut is (
        StatutParcours.DEFI_CLOS
    )
    assert demarrer(present, "l1", YEAR, _manche(), datetime(2026, 12, 5, 22, 30, tzinfo=timezone.utc)).statut is (
        StatutParcours.DEMARRE
    )


def test_sans_date_repas_le_defi_ne_ferme_jamais(present: Path) -> None:
    assert demarrer(present, "l1", YEAR, _manche(), datetime(2030, 1, 1, tzinfo=PARIS)).statut is (
        StatutParcours.DEMARRE
    )


def test_manche_demarree_non_terminee_ne_peut_plus_etre_soumise_apres_cloture(present: Path) -> None:
    _fixer_date_repas(present, "2026-12-05")
    demarrer(present, "l1", YEAR, _manche(), DERNIERE_MINUTE)

    res = soumettre(present, "l1", YEAR, _manche(), JUSTE, PREMIERE_MINUTE)

    assert res.statut is StatutSoumission.DEFI_CLOS
    assert _score(present)["solved"] == 0


def test_etat_derive_close_pour_les_manches_non_terminees(present: Path) -> None:
    _fixer_date_repas(present, "2026-12-05")
    _inserer_score(present, 1, solved=1, attempts=1, time_seconds=40.0, completed=True)
    _inserer_score(present, 2, attempts=1)
    manches = [_manche(id=1), _manche(id=2), _manche(id=3)]

    etats = etat(present, "l1", YEAR, manches, PREMIERE_MINUTE)

    assert [e.statut for e in etats] == [StatutManche.RESOLUE, StatutManche.CLOSE, StatutManche.CLOSE]
    ouverts = etat(present, "l1", YEAR, manches, DERNIERE_MINUTE)
    assert [e.statut for e in ouverts] == [StatutManche.RESOLUE, StatutManche.EN_COURS, StatutManche.DISPONIBLE]
