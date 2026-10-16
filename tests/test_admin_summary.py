"""Tests pour le modèle d'agrégation de l'Espace Admin sous Admin aveugle."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from pere_noel_fremo.admin import DefiInfo, PresenceInfo, TokenInfo, get_admin_edition_summary
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

    # Vérification métriques globales (sur les 4 lutins actifs)
    # Actifs : Albert (confirme), Bernard (absent), Claire (en_attente), Zoé (confirme)
    assert summary["year"] == 2026
    assert summary["status"] == "announced"
    assert summary["total_lutins"] == 4
    assert summary["confirmes"] == 2
    assert summary["absents"] == 1
    assert summary["en_attente"] == 1
    # Tokens envoyés parmi actifs : Albert, Bernard -> 2
    assert summary["tokens_envoyes"] == 2
    # Défi résolus parmi actifs : Albert -> 1
    assert summary["defi_resolus"] == 1
    # Taux de résolution : 1 / 4 * 100 = 25.0 %
    assert summary["taux_resolution_defi"] == 25.0

    # Vérification du dictionnaire metrics dédié
    assert summary["metrics"]["total_lutins"] == 4
    assert summary["metrics"]["confirmes"] == 2
    assert summary["metrics"]["absents"] == 1
    assert summary["metrics"]["en_attente"] == 1
    assert summary["metrics"]["tokens_envoyes"] == 2
    assert summary["metrics"]["defi_resolus"] == 1
    assert summary["metrics"]["taux_resolution_defi"] == 25.0

    # Vérification de la liste des lutins (tous les 5, ordonnés par fullname ASC)
    lutins = summary["lutins"]
    assert len(lutins) == 5
    assert [lutin["fullname"] for lutin in lutins] == [
        "Albert Dupont",
        "Bernard Pivot",
        "Claire Chazal",
        "Ignace Inactif",
        "Zoé Zebra",
    ]

    # Détails Albert
    alb = lutins[0]
    assert alb["id"] == "albert"
    assert alb["is_active"] is True
    assert alb["presence"]["statut"] == "confirme"
    assert alb["presence"]["label"] == "Confirmé"
    assert alb["presence_statut"] == "confirme"
    assert alb["token"]["sent"] is True
    assert alb["token"]["token"] == "tok_alb"
    assert alb["token"] == "tok_alb"
    assert alb["magic_link"] == "/lutin/tok_alb"
    assert alb["defi"]["statut"] == "resolu"
    assert alb["defi"]["label"] == "Résolu"
    assert alb["defi"]["manches_resolues"] == 1
    assert alb["defi"]["time_seconds"] == 45.5
    assert alb["defi"]["attempts"] == 2

    # Détails Bernard
    ber = lutins[1]
    assert ber["id"] == "bernard"
    assert ber["is_active"] is True
    assert ber["presence"]["statut"] == "absent"
    assert ber["presence"]["label"] == "Absent"
    assert ber["token"]["sent"] is True
    assert ber["token"]["token"] == "tok_ber"
    assert ber["defi"]["statut"] == "en_cours"
    assert ber["defi"]["label"] == "En cours"

    # Détails Claire
    cla = lutins[2]
    assert cla["id"] == "claire"
    assert cla["is_active"] is True
    assert cla["presence"]["statut"] == "en_attente"
    assert cla["presence"]["label"] == "En attente"
    assert cla["token"]["sent"] is False
    assert cla["token"]["token"] == "tok_cla"
    assert cla["token"]["sent_at"] is None
    assert cla["defi"]["statut"] == "abandonne"
    assert cla["defi"]["label"] == "Abandonné"

    # Détails Ignace (Inactif)
    ina = lutins[3]
    assert ina["id"] == "inactif"
    assert ina["is_active"] is False
    assert ina["presence"]["statut"] == "confirme"

    # Détails Zoé
    zoe = lutins[4]
    assert zoe["id"] == "zaza"
    assert zoe["is_active"] is True
    assert zoe["presence"]["statut"] == "confirme"
    assert zoe["token"] is None
    assert zoe["token_info"]["token"] is None
    assert zoe["token_info"]["sent"] is False
    assert zoe["magic_link"] is None
    assert zoe["defi"]["statut"] == "non_commence"
    assert zoe["defi"]["label"] == "Non commencé"


def test_admin_summary_all_en_attente(test_db: Path) -> None:
    conn = get_db_connection(test_db)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname, is_active) VALUES ('l1', 'Lutin Un', 1);")
        conn.execute("INSERT INTO lutins (id, fullname, is_active) VALUES ('l2', 'Lutin Deux', 1);")
    conn.close()

    summary = get_admin_edition_summary(test_db, 2026)
    assert summary["total_lutins"] == 2
    assert summary["confirmes"] == 0
    assert summary["absents"] == 0
    assert summary["en_attente"] == 2
    assert summary["tokens_envoyes"] == 0
    assert summary["defi_resolus"] == 0
    assert summary["taux_resolution_defi"] == 0.0

    for lutin_item in summary["lutins"]:
        assert lutin_item["presence"]["statut"] == "en_attente"
        assert lutin_item["presence"]["label"] == "En attente"
        assert lutin_item["token"] is None
        assert lutin_item["token_info"]["token"] is None
        assert lutin_item["token_info"]["sent"] is False
        assert lutin_item["defi"]["statut"] == "non_commence"
        assert lutin_item["defi"]["label"] == "Non commencé"


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
    assert summary_2025["year"] == 2025
    assert summary_2025["status"] == "revealed"
    assert summary_2025["confirmes"] == 1
    assert summary_2025["absents"] == 0
    assert summary_2025["defi_resolus"] == 1
    assert summary_2025["lutins"][0]["presence"]["statut"] == "confirme"
    assert summary_2025["lutins"][0]["defi"]["statut"] == "resolu"
    assert summary_2025["lutins"][0]["token"]["token"] == "tok_2025"

    summary_2026 = get_admin_edition_summary(test_db, 2026)
    assert summary_2026["year"] == 2026
    assert summary_2026["status"] == "announced"
    assert summary_2026["confirmes"] == 0
    assert summary_2026["absents"] == 1
    assert summary_2026["defi_resolus"] == 0
    assert summary_2026["lutins"][0]["presence"]["statut"] == "absent"
    assert summary_2026["lutins"][0]["defi"]["statut"] == "abandonne"
    assert summary_2026["lutins"][0]["token"]["token"] == "tok_2026"

    # Vérification liste des éditions disponibles
    assert 2025 in summary_2026["available_years"]
    assert 2026 in summary_2026["available_years"]


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
    lutins_map = {lutin["id"]: lutin for lutin in summary["lutins"]}

    assert lutins_map["l_multi_solv"]["defi"]["statut"] == "resolu"
    assert lutins_map["l_multi_solv"]["defi"]["manches_resolues"] == 1
    assert lutins_map["l_multi_solv"]["defi"]["attempts"] == 3

    assert lutins_map["l_aban_encours"]["defi"]["statut"] == "en_cours"
    assert lutins_map["l_all_aban"]["defi"]["statut"] == "abandonne"


def test_admin_summary_empty_database(test_db: Path) -> None:
    summary = get_admin_edition_summary(test_db, 2026)
    assert summary["year"] == 2026
    assert summary["total_lutins"] == 0
    assert summary["confirmes"] == 0
    assert summary["absents"] == 0
    assert summary["en_attente"] == 0
    assert summary["tokens_envoyes"] == 0
    assert summary["defi_resolus"] == 0
    assert summary["taux_resolution_defi"] == 0.0
    assert summary["lutins"] == []


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
    for query in queries:
        assert "attribution" not in query.lower(), f"Violation Admin aveugle détectée dans la requête SQL : {query}"
        assert "beneficiaire" not in query.lower(), f"Violation Admin aveugle détectée dans la requête SQL : {query}"
        assert "donneur" not in query.lower(), f"Violation Admin aveugle détectée dans la requête SQL : {query}"

    # 2. Vérifier qu'aucune clé liée aux attributions n'est exposée dans le résultat
    def assert_no_attribution_keys(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                k_lower = str(k).lower()
                assert "attribution" not in k_lower, f"Clé interdite {k} trouvée dans {path}"
                assert "beneficiaire" not in k_lower, f"Clé interdite {k} trouvée dans {path}"
                assert "donneur" not in k_lower, f"Clé interdite {k} trouvée dans {path}"
                assert_no_attribution_keys(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                assert_no_attribution_keys(item, f"{path}[{i}]")

    assert_no_attribution_keys(summary, "summary")


def test_admin_summary_reexport_in_database_module(test_db: Path) -> None:
    from pere_noel_fremo.database import get_admin_edition_summary as db_summary

    assert callable(db_summary)
    res = db_summary(test_db, 2026)
    assert res["year"] == 2026


def test_admin_summary_info_classes_helpers() -> None:
    # PresenceInfo
    p = PresenceInfo(statut="confirme", label="Confirmé", present=True)
    assert p.statut == "confirme"
    assert p.label == "Confirmé"
    assert p.present is True
    assert p == "confirme"
    assert p != "absent"
    assert p == PresenceInfo(statut="confirme", label="Confirmé", present=True)
    assert str(p) == "confirme"

    p_empty = PresenceInfo()
    assert p_empty.statut == ""
    assert p_empty.label == ""
    assert p_empty.present is None

    # TokenInfo
    t = TokenInfo(token="tok_123", sent=True, sent_at="2026-12-01 10:00:00")
    assert t.token == "tok_123"
    assert t.sent is True
    assert t.sent_at == "2026-12-01 10:00:00"
    assert bool(t) is True
    assert t == "tok_123"
    assert t != "tok_other"
    assert t is not None
    assert t.__eq__(None) is False
    assert t != {"token": "tok_other"}
    assert t == {"token": "tok_123", "sent": True, "sent_at": "2026-12-01 10:00:00"}
    assert str(t) == "tok_123"

    t_empty = TokenInfo()
    assert t_empty.token is None
    assert t_empty.sent is False
    assert t_empty.sent_at is None
    assert bool(t_empty) is False
    assert t_empty is not None
    assert t_empty.__eq__(None) is True
    assert t_empty.get("token") is None
    assert str(t_empty) == ""

    # DefiInfo
    d = DefiInfo(statut="resolu", label="Résolu")
    assert d.statut == "resolu"
    assert d.label == "Résolu"
    assert d == "resolu"
    assert d != "abandonne"
    assert d == DefiInfo(statut="resolu", label="Résolu")
    assert str(d) == "resolu"

    d_empty = DefiInfo()
    assert d_empty.statut == ""
    assert d_empty.label == ""
