"""Tests pour le modèle d'agrégation de l'Espace Admin sous Admin aveugle."""

import dataclasses
import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from pere_noel_fremo import admin
from pere_noel_fremo.admin import (
    LutinSuivi,
    MetriquesEdition,
    StatutDefi,
    StatutPresenceAdmin,
    SuiviDefi,
    SuiviLienMagique,
    SuiviPresence,
    SyntheseEdition,
    get_admin_edition_summary,
)
from pere_noel_fremo.database import get_db_connection, init_db


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "test_summary.db"
    init_db(db_file)
    return db_file


@contextmanager
def trace_queries(conn: Any) -> Iterator[list[str]]:
    """Capture toutes les requêtes SQL exécutées sur la connexion."""
    queries: list[str] = []

    def callback(stmt: str) -> None:
        queries.append(stmt)

    conn.set_trace_callback(callback)
    try:
        yield queries
    finally:
        conn.set_trace_callback(None)


def test_admin_summary_nominal(test_db: Path) -> None:
    conn = get_db_connection(test_db)
    with conn:
        conn.execute("INSERT INTO editions (year, status, date_repas) VALUES (2026, 'announced', '2026-12-25');")
        # Lutins (volontairement non triés pour tester le tri par fullname ASC)
        conn.execute(
            "INSERT INTO lutins (id, fullname, email, is_active) VALUES ('zaza', 'Zoé Zebra', 'zoe@ex.com', 1);"
        )
        conn.execute(
            "INSERT INTO lutins (id, fullname, email, is_active) VALUES ('albert', 'Albert Dupont', 'alb@ex.com', 1);"
        )
        conn.execute(
            "INSERT INTO lutins (id, fullname, email, is_active) VALUES ('claire', 'Claire Chazal', 'cla@ex.com', 1);"
        )
        conn.execute(
            "INSERT INTO lutins (id, fullname, email, is_active) VALUES ('bernard', 'Bernard Pivot', 'ber@ex.com', 1);"
        )
        conn.execute(
            "INSERT INTO lutins (id, fullname, email, is_active) VALUES ('inactif', 'Ignace Inactif', 'ign@ex.com', 0);"
        )

        # Présences pour 2026 :
        # - Albert : confirmé (1)
        # - Bernard : absent (0)
        # - Claire : en attente (pas de ligne)
        # - Zoé : confirmé (1)
        # - Inactif : confirmé (1)
        conn.execute("INSERT INTO presences (lutin_id, year, present) VALUES ('albert', 2026, 1);")
        conn.execute("INSERT INTO presences (lutin_id, year, present) VALUES ('bernard', 2026, 0);")
        conn.execute("INSERT INTO presences (lutin_id, year, present) VALUES ('zaza', 2026, 1);")
        conn.execute("INSERT INTO presences (lutin_id, year, present) VALUES ('inactif', 2026, 1);")

        # Tokens pour 2026 :
        # - Albert : envoyé
        # - Bernard : envoyé
        # - Claire : généré mais non envoyé (sent_at IS NULL)
        # - Zoé : pas de token
        conn.execute(
            "INSERT INTO tokens (lutin_id, year, token, sent_at) VALUES ('albert', 2026, 'tok_alb', '2026-11-01');"
        )
        conn.execute(
            "INSERT INTO tokens (lutin_id, year, token, sent_at) VALUES ('bernard', 2026, 'tok_ber', '2026-11-01');"
        )
        conn.execute("INSERT INTO tokens (lutin_id, year, token, sent_at) VALUES ('claire', 2026, 'tok_cla', NULL);")

        # Défi scores pour 2026 :
        # - Albert : résolu (manche 1 résolue)
        # - Bernard : en cours (manche 1 démarrée, non complétée)
        # - Claire : abandonné (manche 1 abandonnée)
        # - Zoé : non commencé (pas de ligne)
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('albert', 2026, 1, 'Lutin Agile', '2026-11-02 12:00:00', 1, 45.5, '2026-11-02 12:00:45', 2);
        """)
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('bernard', 2026, 1, 'Renne Fringant', '2026-11-02 14:00:00', 0, NULL, NULL, 1);
        """)
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('claire', 2026, 1, 'Pingouin Joyeux', '2026-11-02 15:00:00', 0, NULL, '2026-11-02 15:05:00', 3);
        """)
    conn.close()

    summary = get_admin_edition_summary(test_db, 2026)

    assert isinstance(summary, SyntheseEdition)
    assert summary.year == 2026
    assert summary.status == "announced"
    assert summary.date_repas == "2026-12-25"
    # Actifs : Albert (confirme), Bernard (absent), Claire (en_attente), Zoé (confirme)
    assert summary.metrics == MetriquesEdition(
        total_lutins=4,
        confirmes=2,
        absents=1,
        en_attente=1,
        liens_magiques_envoyes=2,  # Albert, Bernard
        defi_resolus=1,  # Albert
        taux_resolution_defi=25.0,
        total_inscrits=5,
        inactifs=1,
    )

    # Tous les 5 lutins, ordonnés par fullname ASC
    lutins = summary.lutins
    assert [lutin.fullname for lutin in lutins] == [
        "Albert Dupont",
        "Bernard Pivot",
        "Claire Chazal",
        "Ignace Inactif",
        "Zoé Zebra",
    ]

    alb = lutins[0]
    assert alb.id == "albert"
    assert alb.email == "alb@ex.com"
    assert alb.is_active is True
    assert alb.presence == SuiviPresence(statut=StatutPresenceAdmin.CONFIRME)
    assert alb.presence.statut == "confirme"
    assert alb.lien_magique == SuiviLienMagique(token="tok_alb", sent_at="2026-11-01")
    assert alb.lien_magique is not None
    assert alb.lien_magique.sent is True
    assert alb.defi == SuiviDefi(
        statut=StatutDefi.RESOLU,
        manches_resolues=1,
        time_seconds=45.5,
        best_time_seconds=45.5,
        attempts=2,
        pseudo_lutin="Lutin Agile",
    )

    ber = lutins[1]
    assert ber.id == "bernard"
    assert ber.presence.statut is StatutPresenceAdmin.ABSENT
    assert ber.lien_magique is not None
    assert ber.lien_magique.sent is True
    assert ber.lien_magique.token == "tok_ber"
    assert ber.defi.statut is StatutDefi.EN_COURS

    cla = lutins[2]
    assert cla.id == "claire"
    assert cla.presence.statut is StatutPresenceAdmin.EN_ATTENTE
    assert cla.lien_magique is not None
    assert cla.lien_magique.sent is False
    assert cla.lien_magique.token == "tok_cla"
    assert cla.lien_magique.sent_at is None
    assert cla.defi.statut is StatutDefi.ABANDONNE

    ina = lutins[3]
    assert ina.id == "inactif"
    assert ina.is_active is False
    assert ina.presence.statut is StatutPresenceAdmin.CONFIRME

    zoe = lutins[4]
    assert zoe.id == "zaza"
    assert zoe.is_active is True
    assert zoe.presence.statut is StatutPresenceAdmin.CONFIRME
    assert zoe.lien_magique is None
    assert zoe.defi.statut is StatutDefi.NON_COMMENCE
    assert zoe.defi.manches_resolues == 0
    assert zoe.defi.time_seconds is None
    assert zoe.defi.pseudo_lutin is None


def test_admin_summary_all_en_attente(test_db: Path) -> None:
    conn = get_db_connection(test_db)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname, is_active) VALUES ('l1', 'Lutin Un', 1);")
        conn.execute("INSERT INTO lutins (id, fullname, is_active) VALUES ('l2', 'Lutin Deux', 1);")
    conn.close()

    summary = get_admin_edition_summary(test_db, 2026)
    assert summary.status == "draft"
    assert summary.date_repas is None
    assert summary.metrics.total_lutins == 2
    assert summary.metrics.confirmes == 0
    assert summary.metrics.absents == 0
    assert summary.metrics.en_attente == 2
    assert summary.metrics.liens_magiques_envoyes == 0
    assert summary.metrics.defi_resolus == 0
    assert summary.metrics.taux_resolution_defi == 0.0

    for lutin_item in summary.lutins:
        assert lutin_item.presence.statut is StatutPresenceAdmin.EN_ATTENTE
        assert lutin_item.lien_magique is None
        assert lutin_item.defi.statut is StatutDefi.NON_COMMENCE


def test_admin_summary_previous_year_historical(test_db: Path) -> None:
    conn = get_db_connection(test_db)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2025, 'revealed');")
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'announced');")
        conn.execute("INSERT INTO lutins (id, fullname, is_active) VALUES ('l1', 'Lutin Test', 1);")

        # 2025: confirmé et résolu
        conn.execute("INSERT INTO presences (lutin_id, year, present) VALUES ('l1', 2025, 1);")
        conn.execute(
            "INSERT INTO tokens (lutin_id, year, token, sent_at) VALUES ('l1', 2025, 'tok_2025', '2025-11-01');"
        )
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('l1', 2025, 1, 'Lutin Ancien', '2025-11-02', 1, 30.0, '2025-11-02', 1);
        """)

        # 2026: absent et abandonné
        conn.execute("INSERT INTO presences (lutin_id, year, present) VALUES ('l1', 2026, 0);")
        conn.execute(
            "INSERT INTO tokens (lutin_id, year, token, sent_at) VALUES ('l1', 2026, 'tok_2026', '2026-11-01');"
        )
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('l1', 2026, 1, 'Lutin Nouveau', '2026-11-02', 0, NULL, '2026-11-02', 2);
        """)
    conn.close()

    summary_2025 = get_admin_edition_summary(test_db, 2025)
    assert summary_2025.year == 2025
    assert summary_2025.status == "revealed"
    assert summary_2025.metrics.confirmes == 1
    assert summary_2025.metrics.absents == 0
    assert summary_2025.metrics.defi_resolus == 1
    assert summary_2025.lutins[0].presence.statut is StatutPresenceAdmin.CONFIRME
    assert summary_2025.lutins[0].defi.statut is StatutDefi.RESOLU
    assert summary_2025.lutins[0].lien_magique is not None
    assert summary_2025.lutins[0].lien_magique.token == "tok_2025"

    summary_2026 = get_admin_edition_summary(test_db, 2026)
    assert summary_2026.year == 2026
    assert summary_2026.status == "announced"
    assert summary_2026.metrics.confirmes == 0
    assert summary_2026.metrics.absents == 1
    assert summary_2026.metrics.defi_resolus == 0
    assert summary_2026.lutins[0].presence.statut is StatutPresenceAdmin.ABSENT
    assert summary_2026.lutins[0].defi.statut is StatutDefi.ABANDONNE
    assert summary_2026.lutins[0].lien_magique is not None
    assert summary_2026.lutins[0].lien_magique.token == "tok_2026"

    # Vérification liste des éditions disponibles
    assert summary_2026.available_years == [2026, 2025]


def test_admin_summary_defi_multi_manches_hierarchy(test_db: Path) -> None:
    conn = get_db_connection(test_db)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'announced');")
        conn.execute("INSERT INTO lutins (id, fullname, is_active) VALUES ('l_multi_solv', 'Lutin Gagnant', 1);")
        conn.execute("INSERT INTO lutins (id, fullname, is_active) VALUES ('l_aban_encours', 'Lutin En cours', 1);")
        conn.execute("INSERT INTO lutins (id, fullname, is_active) VALUES ('l_all_aban', 'Lutin Abandon', 1);")

        # Lutin Gagnant : Manche 1 abandonnée, Manche 2 résolue -> statut 'resolu'
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('l_multi_solv', 2026, 1, 'P1', '2026-11-01', 0, NULL, '2026-11-01', 1);
        """)
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('l_multi_solv', 2026, 2, 'P1', '2026-11-02', 1, 60.0, '2026-11-02', 2);
        """)

        # Lutin En cours : Manche 1 abandonnée, Manche 2 démarrée non complétée -> statut 'en_cours'
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('l_aban_encours', 2026, 1, 'P2', '2026-11-01', 0, NULL, '2026-11-01', 1);
        """)
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('l_aban_encours', 2026, 2, 'P2', '2026-11-02', 0, NULL, NULL, 0);
        """)

        # Lutin Abandon : Manche 1 abandonnée, Manche 2 abandonnée -> statut 'abandonne'
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('l_all_aban', 2026, 1, 'P3', '2026-11-01', 0, NULL, '2026-11-01', 1);
        """)
        conn.execute("""
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at, attempts
            ) VALUES ('l_all_aban', 2026, 2, 'P3', '2026-11-02', 0, NULL, '2026-11-02', 2);
        """)
    conn.close()

    summary = get_admin_edition_summary(test_db, 2026)
    lutins_map = {lutin.id: lutin for lutin in summary.lutins}

    assert lutins_map["l_multi_solv"].defi.statut is StatutDefi.RESOLU
    assert lutins_map["l_multi_solv"].defi.manches_resolues == 1
    assert lutins_map["l_multi_solv"].defi.attempts == 3

    assert lutins_map["l_aban_encours"].defi.statut is StatutDefi.EN_COURS
    assert lutins_map["l_all_aban"].defi.statut is StatutDefi.ABANDONNE


def test_admin_summary_empty_database(test_db: Path) -> None:
    summary = get_admin_edition_summary(test_db, 2026)
    assert summary.year == 2026
    assert summary.available_years == [2026]
    assert summary.metrics == MetriquesEdition(
        total_lutins=0,
        confirmes=0,
        absents=0,
        en_attente=0,
        liens_magiques_envoyes=0,
        defi_resolus=0,
        taux_resolution_defi=0.0,
        total_inscrits=0,
        inactifs=0,
    )
    assert summary.lutins == []


def test_admin_summary_strict_blind_admin_guarantee(test_db: Path) -> None:
    """Garantie absolue d'Admin aveugle (ADR-0005, ADR-0013) :
    Aucune requête SQL ne doit mentionner 'attributions', et le dictionnaire retourné
    ne doit contenir aucun couple Donneur-Bénéficiaire ni aucune clé liée aux attributions.
    """
    conn = get_db_connection(test_db)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'drawn');")
        conn.execute("INSERT INTO lutins (id, fullname, is_active) VALUES ('l1', 'Donneur A', 1);")
        conn.execute("INSERT INTO lutins (id, fullname, is_active) VALUES ('l2', 'Bénéficiaire B', 1);")
        conn.execute("INSERT INTO presences (lutin_id, year, present) VALUES ('l1', 2026, 1);")
        conn.execute("INSERT INTO presences (lutin_id, year, present) VALUES ('l2', 2026, 1);")
        # Insertion d'attributions dans la table
        conn.execute(
            "INSERT INTO attributions (donneur_id, beneficiaire_id, year, order_index) VALUES ('l1', 'l2', 2026, 0);"
        )
        conn.execute(
            "INSERT INTO attributions (donneur_id, beneficiaire_id, year, order_index) VALUES ('l2', 'l1', 2026, 0);"
        )

    with trace_queries(conn) as queries:
        summary = get_admin_edition_summary(conn, 2026)

    conn.close()

    # 1. Vérifier que la table attributions n'a JAMAIS été consultée par SQL
    assert queries, "aucune requête tracée"
    for query in queries:
        assert "attribution" not in query.lower(), f"Violation Admin aveugle détectée dans la requête SQL : {query}"
        assert "beneficiaire" not in query.lower(), f"Violation Admin aveugle détectée dans la requête SQL : {query}"
        assert "donneur" not in query.lower(), f"Violation Admin aveugle détectée dans la requête SQL : {query}"

    # 2. Vérifier qu'aucun champ lié aux attributions n'est exposé dans le résultat
    def field_names(obj: Any) -> set[str]:
        names: set[str] = set()
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            for f in dataclasses.fields(obj):
                names.add(f.name)
                names |= field_names(getattr(obj, f.name))
        elif isinstance(obj, list):
            for item in obj:
                names |= field_names(item)
        return names

    names = field_names(summary)
    assert {"lutins", "metrics", "presence", "defi"} <= names
    for name in names:
        assert not any(bad in name.lower() for bad in ("attribution", "beneficiaire", "donneur")), name


def test_admin_summary_reexport_in_database_module(test_db: Path) -> None:
    from pere_noel_fremo.database import get_admin_edition_summary as db_summary

    assert callable(db_summary)
    res = db_summary(test_db, 2026)
    assert res.year == 2026


def test_admin_summary_is_made_of_frozen_dataclasses_only() -> None:
    """Plus aucune sous-classe de dict dans admin.py ; tout le résultat est figé."""
    for _, obj in inspect.getmembers(admin, inspect.isclass):
        if obj.__module__ == admin.__name__:
            assert not issubclass(obj, dict), obj
    for cls in (SyntheseEdition, MetriquesEdition, LutinSuivi, SuiviPresence, SuiviLienMagique, SuiviDefi):
        assert dataclasses.is_dataclass(cls)
        assert getattr(cls, "__dataclass_params__").frozen  # noqa: B009


def test_admin_summary_has_a_single_name_per_datum(test_db: Path) -> None:
    conn = get_db_connection(test_db)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname, is_active) VALUES ('l1', 'Lutin', 1);")
        conn.execute("INSERT INTO tokens (lutin_id, year, token) VALUES ('l1', 2026, 'tok_x');")
    conn.close()

    lutin = get_admin_edition_summary(test_db, 2026).lutins[0]
    assert {f.name for f in dataclasses.fields(lutin)} == {
        "id",
        "fullname",
        "email",
        "is_active",
        "presence",
        "lien_magique",
        "defi",
    }
    assert lutin.lien_magique is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        lutin.fullname = "autre"  # type: ignore[misc]
    assert repr(lutin).count("tok_x") == 1
