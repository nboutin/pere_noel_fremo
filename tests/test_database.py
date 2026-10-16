import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml
from pere_noel_fremo.database import (
    PresencesChangees,
    get_attributions,
    get_beneficiaire_for_lutin,
    get_confirmed_lutins,
    get_db_connection,
    get_edition_date_repas,
    get_edition_status,
    get_lutins,
    get_score_defi,
    get_scores_classement,
    historique_avant,
    import_yaml_data,
    init_db,
    save_attributions,
    set_edition_status,
    set_lutin_presence,
    start_score_defi,
)
from pere_noel_fremo.parcours import StatutSoumission


def test_init_db_creates_all_required_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    conn = get_db_connection(db_path)

    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()

    required_tables = {
        "lutins",
        "exclusions",
        "editions",
        "tokens",
        "presences",
        "scores_defi",
        "attributions",
        "pseudos",
    }
    assert required_tables.issubset(tables)


def test_init_db_enables_foreign_keys_and_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    init_db(db_path)
    conn2 = get_db_connection(db_path)
    cursor = conn2.cursor()
    cursor.execute("PRAGMA foreign_keys;")
    fk_status = cursor.fetchone()[0]
    conn2.close()

    assert fk_status == 1


def test_import_yaml_data_and_get_lutins(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data = {
        "lutin_a": {
            "fullname": "Lutin A",
            "email": None,
            "exclude": ["lutin_b"],
            "history": ["lutin_b", "lutin_c"],
        },
        "lutin_b": {
            "fullname": "Lutin B",
            "email": None,
            "exclude": ["lutin_a"],
            "history": ["lutin_a"],
        },
        "lutin_c": {
            "fullname": "Lutin C",
            "email": None,
            "exclude": [],
            "history": [],
        },
    }
    sample_secure = {
        "personnes": {
            "lutin_a": {"email": "lutin_a@fremo.org"},
            "lutin_b": {"email": "lutin_b@fremo.org"},
            "lutin_c": {"email": "lutin_c@fremo.org"},
        }
    }

    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_secure, f)

    # First import
    counts = import_yaml_data(db_path, data_in_path, secure_data_path)
    assert counts["lutins"] == 3
    assert counts["exclusions"] == 2
    assert counts["attributions"] == 3

    # Verify retrieved lutins structure
    lutins = get_lutins(db_path)
    assert len(lutins) == 3
    assert lutins["lutin_a"]["fullname"] == "Lutin A"
    assert lutins["lutin_a"]["email"] == "lutin_a@fremo.org"
    assert lutins["lutin_a"]["exclude"] == ["lutin_b"]
    assert lutins["lutin_a"]["history"] == ["lutin_b", "lutin_c"]

    # Test idempotence: running import a second time updates or preserves without duplicate keys/rows
    counts_repeat = import_yaml_data(db_path, data_in_path, secure_data_path)
    assert counts_repeat["lutins"] == 3

    lutins_after = get_lutins(db_path)
    assert lutins_after["lutin_a"]["history"] == ["lutin_b", "lutin_c"]
    assert lutins_after["lutin_a"]["exclude"] == ["lutin_b"]


def _seed_historique(db_path: Path) -> None:
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        for lutin_id in ("a", "b", "c"):
            conn.execute("INSERT INTO lutins (id, fullname) VALUES (?, ?);", (lutin_id, lutin_id))
        for year in (2024, 2025, 2026, 2027):
            conn.execute("INSERT INTO editions (year, status) VALUES (?, 'drawn');", (year,))
        rows = [("a", "b", 2024, 0), ("a", "c", 2025, 1), ("a", "b", 2026, 2), ("a", "c", 2027, 3)]
        for donneur, beneficiaire, year, idx in rows:
            conn.execute(
                "INSERT INTO attributions (donneur_id, beneficiaire_id, year, order_index) VALUES (?, ?, ?, ?);",
                (donneur, beneficiaire, year, idx),
            )
    conn.close()


def test_historique_avant_is_strictly_before_year_and_deduplicated(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    _seed_historique(db_path)

    assert historique_avant(db_path, 2026) == {"a": ["b", "c"]}
    assert historique_avant(db_path, 2025) == {"a": ["b"]}
    assert historique_avant(db_path, 2024) == {}
    conn = get_db_connection(db_path)
    try:
        assert historique_avant(conn, 2030) == {"a": ["b", "c"]}
    finally:
        conn.close()


def test_import_yaml_data_validates_referential_integrity(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    # lutin_a excludes unknown_lutin
    invalid_data = {
        "lutin_a": {
            "fullname": "Lutin A",
            "email": None,
            "exclude": ["ghost_lutin"],
            "history": [],
        }
    }
    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.dump(invalid_data, f)
    with open(secure_data_path, "w", encoding="utf-8") as f:
        yaml.dump({"personnes": {}}, f)

    with pytest.raises(ValueError, match="ghost_lutin"):
        import_yaml_data(db_path, data_in_path, secure_data_path)


def test_import_real_res_data_if_present(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    data_in_path = root / "res" / "2025" / "data_in.yml"
    secure_data_path = root / "res" / "secure_data.yml"

    if not data_in_path.exists() or not secure_data_path.exists():
        pytest.skip("Repository res files not found")

    db_path = tmp_path / "fremo_real.db"
    counts = import_yaml_data(db_path, data_in_path, secure_data_path)
    assert counts["lutins"] > 0
    assert counts["exclusions"] > 0
    assert counts["attributions"] > 0

    lutins = get_lutins(db_path)
    assert len(lutins) == counts["lutins"]


def test_database_foreign_key_constraints(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    conn = get_db_connection(db_path)

    # Attempting to insert an exclusion with non-existent lutin must fail FK constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO exclusions (lutin_id, excluded_lutin_id) VALUES ('non_existent', 'unknown');")

    # Attempting to insert an attribution with non-existent donneur_id must fail FK constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO attributions (donneur_id, beneficiaire_id, year, order_index) VALUES ('x', 'y', NULL, 0);"
        )

    conn.close()


def test_confirmed_lutins_and_save_attributions(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('lutin_1', 'Lutin 1', 'l1@fremo.org');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('lutin_2', 'Lutin 2', 'l2@fremo.org');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('lutin_3', 'Lutin 3', 'l3@fremo.org');")
    conn.close()

    # Confirmer lutin_1 et lutin_2 comme présents, lutin_3 comme absent
    set_lutin_presence(db_path, "lutin_1", 2026, present=True)
    set_lutin_presence(db_path, "lutin_2", 2026, present=True)
    set_lutin_presence(db_path, "lutin_3", 2026, present=False)

    confirmed = get_confirmed_lutins(db_path, 2026)
    assert set(confirmed.keys()) == {"lutin_1", "lutin_2"}
    assert "lutin_3" not in confirmed

    # Sauvegarder les attributions
    attributions = {"lutin_1": "lutin_2", "lutin_2": "lutin_1"}
    save_attributions(db_path, 2026, attributions)

    assert get_edition_status(db_path, 2026) == "drawn"
    saved = get_attributions(db_path, 2026)
    assert saved == attributions

    # Idempotence / update attributions: réenregistrement met à jour sans collision
    attributions_updated = {"lutin_1": "lutin_2", "lutin_2": "lutin_1"}
    save_attributions(db_path, 2026, attributions_updated)
    assert get_attributions(db_path, 2026) == attributions_updated


def test_scores_defi_and_beneficiaire_operations(tmp_path: Path, solve_manche: Callable[..., dict[str, Any]]) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l1', 'Lutin 1', 'l1@fremo.org');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l2', 'Lutin 2', 'l2@fremo.org');")
    conn.close()

    # 1. Attributions & get_beneficiaire_for_lutin
    set_lutin_presence(db_path, "l1", 2026, present=True)
    set_lutin_presence(db_path, "l2", 2026, present=True)
    save_attributions(db_path, 2026, {"l1": "l2", "l2": "l1"})
    beneficiaire = get_beneficiaire_for_lutin(db_path, "l1", 2026)
    assert beneficiaire is not None
    assert beneficiaire["id"] == "l2"
    assert beneficiaire["fullname"] == "Lutin 2"

    # Donneur inexistant ou sans attribution
    assert get_beneficiaire_for_lutin(db_path, "l_inconnu", 2026) is None

    # 2. Score Défi cycle de vie
    assert get_score_defi(db_path, "l1", 2026) == {}

    # Démarrage
    started = start_score_defi(db_path, "l1", 2026, "Renne Agile")
    assert started["lutin_id"] == "l1"
    assert started["pseudo_lutin"] == "Renne Agile"
    assert started["solved"] == 0
    assert started["started_at"] is not None

    # Complétion via le chemin de production (premier essai, sans pénalité)
    t0 = datetime(2026, 10, 14, 20, 0, 0, tzinfo=timezone.utc)
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("UPDATE scores_defi SET started_at = ? WHERE lutin_id = 'l1';", (t0.isoformat(),))
    conn.close()
    result = solve_manche(db_path, "l1", 2026, 42.5)
    assert result["statut"] is StatutSoumission.RESOLUE
    completed = get_score_defi(db_path, "l1", 2026)
    assert completed["solved"] == 1
    assert completed["time_seconds"] == 42.5

    # Idempotence complétion (ne modifie pas un score déjà résolu)
    again = solve_manche(db_path, "l1", 2026, 999)
    assert again["statut"] is StatutSoumission.DEJA_TERMINEE
    assert get_score_defi(db_path, "l1", 2026)["time_seconds"] == 42.5

    # 3. Classement ordonné
    solve_manche(db_path, "l2", 2026, 30.0, pseudo_lutin="Lutin Givré")

    classement = get_scores_classement(db_path, 2026)
    assert len(classement) == 2
    # l2 (30.0s) doit être 1er devant l1 (42.5s)
    assert classement[0]["pseudo_lutin"] == "Lutin Givré"
    assert classement[0]["time_seconds"] == 30.0
    assert classement[1]["pseudo_lutin"] == "Renne Agile"
    assert classement[1]["time_seconds"] == 42.5


def test_scores_defi_multi_manches(tmp_path: Path, solve_manche: Callable[..., dict[str, Any]]) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l1', 'Lutin 1', 'l1@fremo.org');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l2', 'Lutin 2', 'l2@fremo.org');")
    conn.close()

    # Lutin 1 joue la manche 1 et la manche 2
    # Complétion manche 1 : l2 (25s), l1 (50s)
    score_m1 = solve_manche(db_path, "l1", 2026, 50.0, pseudo_lutin="Renne Agile", manche_id=1)
    solve_manche(db_path, "l2", 2026, 25.0, pseudo_lutin="Lutin Givré", manche_id=1)

    # Complétion manche 2 : l1 (35s)
    score_m2 = solve_manche(db_path, "l1", 2026, 35.0, pseudo_lutin="Renne Agile", manche_id=2)
    assert score_m1["time_seconds"] == 50.0
    assert score_m2["time_seconds"] == 35.0

    # Classement Manche 1
    classement_m1 = get_scores_classement(db_path, 2026, manche_id=1)
    assert len(classement_m1) == 2
    assert classement_m1[0]["pseudo_lutin"] == "Lutin Givré"
    assert classement_m1[0]["time_seconds"] == 25.0
    assert classement_m1[1]["pseudo_lutin"] == "Renne Agile"
    assert classement_m1[1]["time_seconds"] == 50.0

    # Classement Manche 2
    classement_m2 = get_scores_classement(db_path, 2026, manche_id=2)
    assert len(classement_m2) == 1
    assert classement_m2[0]["pseudo_lutin"] == "Renne Agile"
    assert classement_m2[0]["time_seconds"] == 35.0


def test_scores_defi_schema_migration_idempotent(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "fremo_legacy.db"
    conn = sqlite3.connect(str(db_path))
    # Création d'une base avec l'ancien schéma sans manche_id dans la PK
    conn.executescript("""
        CREATE TABLE editions (year INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'draft');
        CREATE TABLE lutins (
            id TEXT PRIMARY KEY,
            fullname TEXT NOT NULL,
            email TEXT,
            is_active BOOLEAN NOT NULL DEFAULT 1
        );
        CREATE TABLE scores_defi (
            lutin_id TEXT NOT NULL REFERENCES lutins(id),
            year INTEGER NOT NULL REFERENCES editions(year),
            pseudo_lugeur TEXT NOT NULL,
            solved BOOLEAN NOT NULL DEFAULT 0,
            time_seconds REAL,
            completed_at TIMESTAMP,
            PRIMARY KEY (lutin_id, year)
        );
        INSERT INTO editions (year, status) VALUES (2026, 'draft');
        INSERT INTO lutins (id, fullname) VALUES ('l1', 'Lutin 1');
        INSERT INTO scores_defi (lutin_id, year, pseudo_lugeur, solved, time_seconds)
        VALUES ('l1', 2026, 'Lutin Ancien', 1, 45.0);
    """)
    conn.close()

    # Exécution de init_db qui doit appliquer la migration
    init_db(db_path)

    # Vérification que le score existant a manche_id = 1
    scores_m1 = get_scores_classement(db_path, 2026, manche_id=1)
    assert len(scores_m1) == 1
    assert scores_m1[0]["pseudo_lutin"] == "Lutin Ancien"
    assert scores_m1[0]["time_seconds"] == 45.0
    assert scores_m1[0]["manche_id"] == 1

    # Insertion d'une manche 2 pour le même lutin (doit réussir grâce à la clé composite)
    score_m2 = start_score_defi(db_path, "l1", 2026, "Lutin Ancien", manche_id=2)
    assert score_m2["manche_id"] == 2

    # Deuxième appel à init_db pour vérifier l'idempotence
    init_db(db_path)
    scores_all = get_scores_classement(db_path, 2026)
    assert len(scores_all) == 2


def test_save_attributions_successive_draws_no_order_index_hole(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO editions (year, status) VALUES (2024, 'drawn'), (2025, 'drawn'), (2026, 'draft');"
            )
            conn.execute(
                "INSERT INTO lutins (id, fullname) VALUES "
                "('g1', 'Giver 1'), ('r1', 'Receiver 1'), ('r2', 'Receiver 2'), ('r3', 'Receiver 3');"
            )
            # Historique : order_index 0 (2024), 1 (2025)
            conn.execute(
                "INSERT INTO attributions (donneur_id, beneficiaire_id, year, order_index) "
                "VALUES ('g1', 'r1', 2024, 0);"
            )
            conn.execute(
                "INSERT INTO attributions (donneur_id, beneficiaire_id, year, order_index) "
                "VALUES ('g1', 'r2', 2025, 1);"
            )
    finally:
        conn.close()

    # Premier tirage 2026 : donneur 'g1' reçoit l'attribution vers 'r3'
    set_lutin_presence(db_path, "g1", 2026, present=True)
    save_attributions(db_path, 2026, {"g1": "r3"})

    conn = get_db_connection(db_path)
    try:
        row = conn.execute("SELECT order_index FROM attributions WHERE donneur_id = 'g1' AND year = 2026;").fetchone()
        assert row is not None
        assert row["order_index"] == 2
    finally:
        conn.close()

    # Deuxième tirage (re-tirage pour la même année 2026) avec une cible différente (ou identique)
    save_attributions(db_path, 2026, {"g1": "r2"})

    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT order_index, beneficiaire_id FROM attributions WHERE donneur_id = 'g1' AND year = 2026;"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["order_index"] == 2
        assert rows[0]["beneficiaire_id"] == "r2"

        # Vérifier l'ensemble de la séquence d'ordre pour g1 : [0, 1, 2] sans aucun trou
        all_indices = [
            r["order_index"]
            for r in conn.execute(
                "SELECT order_index FROM attributions WHERE donneur_id = 'g1' ORDER BY order_index ASC;"
            ).fetchall()
        ]
        assert all_indices == [0, 1, 2]
    finally:
        conn.close()


def test_init_db_adds_date_repas_column_and_migration(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "legacy_editions.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE editions (year INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'draft');")
    conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
    conn.commit()
    conn.close()

    # init_db doit migrer la table pour ajouter date_repas
    init_db(db_path)
    conn_migrated = get_db_connection(db_path)
    cols = [row[1] for row in conn_migrated.execute("PRAGMA table_info(editions);").fetchall()]
    conn_migrated.close()
    assert "date_repas" in cols


def test_import_yaml_data_with_edition_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo_meta.db"
    data_in_path = tmp_path / "data_in.yml"
    secure_data_path = tmp_path / "secure_data.yml"

    sample_data = {
        "_edition": {
            "date_repas": "2026-12-05",
        },
        "lutin_1": {
            "fullname": "Lutin Un",
            "email": "l1@example.com",
            "exclude": [],
            "history": [],
        },
        "lutin_2": {
            "fullname": "Lutin Deux",
            "email": "l2@example.com",
            "exclude": [],
            "history": [],
        },
    }
    with open(data_in_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(sample_data, f)

    res = import_yaml_data(db_path, data_in_path, secure_data_path, year=2026)
    assert res["lutins"] == 2

    # Vérifier que _edition n'est pas inséré comme lutin
    lutins = get_lutins(db_path)
    lutin_ids = list(lutins.keys())
    assert "_edition" not in lutin_ids
    assert "lutin_1" in lutin_ids
    assert "lutin_2" in lutin_ids

    # Vérifier que date_repas est bien persistée dans editions
    date_repas = get_edition_date_repas(db_path, 2026)
    assert date_repas == "2026-12-05"


def test_get_edition_date_repas_non_existent(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    init_db(db_path)
    assert get_edition_date_repas(db_path, 2099) is None


def test_init_db_adds_attempts_column_and_migrates_data(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "legacy_scores.db"
    conn = sqlite3.connect(str(db_path))
    # Créer les tables minimales avec un scores_defi sans la colonne attempts
    conn.execute("CREATE TABLE editions (year INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'draft');")
    conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
    conn.execute("CREATE TABLE lutins (id TEXT PRIMARY KEY, fullname TEXT NOT NULL, email TEXT);")
    conn.execute("INSERT INTO lutins (id, fullname) VALUES ('l1', 'Lutin 1');")
    conn.execute("INSERT INTO lutins (id, fullname) VALUES ('l2', 'Lutin 2');")
    conn.execute("""
        CREATE TABLE scores_defi (
            lutin_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
            year INTEGER NOT NULL REFERENCES editions(year) ON DELETE CASCADE,
            manche_id INTEGER NOT NULL DEFAULT 1,
            pseudo_lugeur TEXT NOT NULL,
            started_at TIMESTAMP,
            solved BOOLEAN NOT NULL DEFAULT 0,
            time_seconds REAL,
            completed_at TIMESTAMP,
            PRIMARY KEY (lutin_id, year, manche_id)
        );
    """)
    # l1 a résolu la manche -> attempts doit devenir 1
    conn.execute("""
        INSERT INTO scores_defi (
            lutin_id, year, manche_id, pseudo_lugeur, started_at, solved, time_seconds, completed_at
        )
        VALUES ('l1', 2026, 1, 'Renne Agile', '2026-10-14 20:00:00', 1, 42.0, '2026-10-14 20:00:42');
    """)
    # l2 n'a pas résolu la manche -> attempts doit devenir 0
    conn.execute("""
        INSERT INTO scores_defi (
            lutin_id, year, manche_id, pseudo_lugeur, started_at, solved, time_seconds, completed_at
        )
        VALUES ('l2', 2026, 1, 'Lutin Givré', '2026-10-14 20:00:00', 0, NULL, NULL);
    """)
    conn.commit()
    conn.close()

    # Migration idempotente via init_db
    init_db(db_path)

    conn_check = get_db_connection(db_path)
    cols = [r[1] for r in conn_check.execute("PRAGMA table_info(scores_defi);").fetchall()]
    assert "attempts" in cols

    l1_row = conn_check.execute("SELECT attempts, solved FROM scores_defi WHERE lutin_id = 'l1';").fetchone()
    assert l1_row["attempts"] == 1
    assert l1_row["solved"] == 1

    l2_row = conn_check.execute("SELECT attempts, solved FROM scores_defi WHERE lutin_id = 'l2';").fetchone()
    assert l2_row["attempts"] == 0
    assert l2_row["solved"] == 0
    conn_check.close()

    # Idempotence d'un deuxième appel
    init_db(db_path)
    conn_check2 = get_db_connection(db_path)
    l1_row2 = conn_check2.execute("SELECT attempts FROM scores_defi WHERE lutin_id = 'l1';").fetchone()
    assert l1_row2["attempts"] == 1
    conn_check2.close()


def test_get_or_assign_pseudo_all_26_lutins_from_res_2025_get_unique_pseudos(tmp_path: Path) -> None:
    from pere_noel_fremo.database import get_or_assign_pseudo

    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    res_data_in = Path("res/2025/data_in.yml")
    with open(res_data_in, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    lutin_ids = list(data.keys())
    assert len(lutin_ids) == 26

    assigned_pseudos = {}
    for lid in lutin_ids:
        p = get_or_assign_pseudo(db_path, lid, 2026)
        assigned_pseudos[lid] = p

    # 26 pseudos distincts
    assert len(set(assigned_pseudos.values())) == 26

    # Deux appels successifs renvoient le même pseudo (stabilité/idempotence)
    for lid in lutin_ids:
        assert get_or_assign_pseudo(db_path, lid, 2026) == assigned_pseudos[lid]


def test_get_or_assign_pseudo_raises_when_space_exhausted(tmp_path: Path) -> None:
    from pere_noel_fremo.database import get_or_assign_pseudo
    from pere_noel_fremo.defi import ADJECTIFS_FESTIFS, ANIMAUX_LUTINS

    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    max_pseudos = len(ANIMAUX_LUTINS) * len(ADJECTIFS_FESTIFS)
    assert max_pseudos == 180

    for i in range(max_pseudos):
        get_or_assign_pseudo(db_path, f"lutin_{i}", 2026)

    # Le 181e tirage doit lever une RuntimeError ou ValueError
    with pytest.raises((RuntimeError, ValueError), match="épuisé"):
        get_or_assign_pseudo(db_path, "lutin_overflow", 2026)


def test_migration_scores_defi_with_duplicate_pseudos_assigns_unique_pseudos(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo_legacy.db"
    # Créer une base simulant l'ancien schéma avec scores_defi sans table pseudos
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.executescript("""
        CREATE TABLE editions (year INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'draft');
        CREATE TABLE lutins (id TEXT PRIMARY KEY, fullname TEXT NOT NULL, email TEXT);
        CREATE TABLE scores_defi (
            lutin_id TEXT NOT NULL,
            year INTEGER NOT NULL,
            manche_id INTEGER NOT NULL DEFAULT 1,
            pseudo_lugeur TEXT NOT NULL,
            started_at TIMESTAMP,
            solved BOOLEAN NOT NULL DEFAULT 0,
            time_seconds REAL,
            completed_at TIMESTAMP,
            attempts INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (lutin_id, year, manche_id)
        );
        INSERT INTO editions (year) VALUES (2026);
        INSERT INTO lutins (id, fullname) VALUES ('jdenis', 'Jean Denis'), ('mdenis', 'Marc Denis');
        INSERT INTO scores_defi (lutin_id, year, manche_id, pseudo_lugeur, solved, time_seconds)
        VALUES ('jdenis', 2026, 1, 'Lutin Givré', 1, 30.0),
               ('mdenis', 2026, 1, 'Lutin Givré', 1, 45.0);
    """)
    conn.commit()
    conn.close()

    # Exécution de la migration idempotente
    init_db(db_path)

    conn2 = get_db_connection(db_path)
    p_jdenis = conn2.execute("SELECT pseudo FROM pseudos WHERE year = 2026 AND lutin_id = 'jdenis';").fetchone()
    p_mdenis = conn2.execute("SELECT pseudo FROM pseudos WHERE year = 2026 AND lutin_id = 'mdenis';").fetchone()
    assert p_jdenis is not None
    assert p_mdenis is not None
    assert p_jdenis["pseudo"] != p_mdenis["pseudo"]

    # scores_defi doit refléter ces pseudos distincts
    row_j = conn2.execute("SELECT pseudo_lutin FROM scores_defi WHERE lutin_id = 'jdenis';").fetchone()
    row_m = conn2.execute("SELECT pseudo_lutin FROM scores_defi WHERE lutin_id = 'mdenis';").fetchone()
    assert row_j["pseudo_lutin"] == p_jdenis["pseudo"]
    assert row_m["pseudo_lutin"] == p_mdenis["pseudo"]
    assert row_j["pseudo_lutin"] != row_m["pseudo_lutin"]
    conn2.close()


def test_get_scores_classement_includes_lutin_id(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname) VALUES ('jdenis', 'Jean Denis');")
    conn.close()

    start_score_defi(db_path, "jdenis", 2026, pseudo_lutin="Renne Agile", manche_id=1)
    scores = get_scores_classement(db_path, 2026, manche_id=1)
    assert len(scores) == 1
    assert "lutin_id" in scores[0]
    assert scores[0]["lutin_id"] == "jdenis"
    assert scores[0]["pseudo_lutin"] == "Renne Agile"
    assert scores[0]["pseudo_lutin"] == "Renne Agile"


def test_parse_iso_or_legacy() -> None:
    from datetime import datetime, timezone

    from pere_noel_fremo.database import parse_iso_or_legacy

    # 1. Format legacy SQLite (%Y-%m-%d %H:%M:%S)
    legacy_dt = parse_iso_or_legacy("2026-10-14 20:00:00")
    assert legacy_dt == datetime(2026, 10, 14, 20, 0, 0, tzinfo=timezone.utc)

    # 2. Format ISO-8601 avec millisecondes et fuseau
    iso_ms_dt = parse_iso_or_legacy("2026-10-14T20:00:00.123456+00:00")
    assert iso_ms_dt == datetime(2026, 10, 14, 20, 0, 0, 123456, tzinfo=timezone.utc)

    # 3. Format ISO-8601 avec suffixe Z
    iso_z_dt = parse_iso_or_legacy("2026-10-14T20:00:00.123Z")
    assert iso_z_dt == datetime(2026, 10, 14, 20, 0, 0, 123000, tzinfo=timezone.utc)

    # 4. Objet datetime direct (aware et naive)
    naive_dt = datetime(2026, 10, 14, 20, 0, 0)
    assert parse_iso_or_legacy(naive_dt) == datetime(2026, 10, 14, 20, 0, 0, tzinfo=timezone.utc)


def test_parse_iso_or_legacy_accepts_z_suffix_on_python_310() -> None:
    """Python 3.10 refuse le suffixe Z dans fromisoformat : parse_iso_or_legacy doit le normaliser."""
    from datetime import datetime, timezone

    from pere_noel_fremo.database import parse_iso_or_legacy

    expected = datetime(2026, 10, 14, 20, 0, 0, tzinfo=timezone.utc)
    assert parse_iso_or_legacy("2026-10-14T20:00:00Z") == expected
    assert parse_iso_or_legacy("2026-10-14T20:00:00z") == expected
    assert parse_iso_or_legacy(" 2026-10-14T20:00:00Z ") == expected


def test_migration_purges_unstarted_scores(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo_purge.db"
    init_db(db_path)

    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname) VALUES ('l1', 'Lutin 1');")
        conn.execute("INSERT INTO lutins (id, fullname) VALUES ('l2', 'Lutin 2');")
        conn.execute("INSERT INTO lutins (id, fullname) VALUES ('l3', 'Lutin 3');")
        # Row 1: non démarré (started_at IS NULL)
        conn.execute(
            "INSERT INTO scores_defi (lutin_id, year, manche_id, pseudo_lutin, started_at, solved) "
            "VALUES ('l1', 2026, 1, 'Lutin Un', NULL, 0);"
        )
        # Row 2: démarré et résolu
        conn.execute(
            """
            INSERT INTO scores_defi (
                lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds, completed_at
            ) VALUES (
                'l2', 2026, 1, 'Lutin Deux', '2026-10-14T20:00:00.123456+00:00',
                1, 35.2, '2026-10-14T20:00:35.323456+00:00'
            );
            """
        )
        # Row 3: démarré en cours (format legacy)
        conn.execute(
            "INSERT INTO scores_defi (lutin_id, year, manche_id, pseudo_lutin, started_at, solved) "
            "VALUES ('l3', 2026, 1, 'Lutin Trois', '2026-10-14 20:00:00', 0);"
        )
    conn.close()

    # Exécution de init_db qui doit purger les lignes sans started_at
    init_db(db_path)

    conn = get_db_connection(db_path)
    rows = conn.execute("SELECT lutin_id, started_at FROM scores_defi ORDER BY lutin_id;").fetchall()
    conn.close()

    assert len(rows) == 2
    lutin_ids = [r["lutin_id"] for r in rows]
    assert "l1" not in lutin_ids
    assert "l2" in lutin_ids
    assert "l3" in lutin_ids


def test_get_scores_classement_filters_unstarted_participants(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo_filter.db"
    init_db(db_path)

    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname) VALUES ('l1', 'Lutin 1');")
        conn.execute("INSERT INTO lutins (id, fullname) VALUES ('l2', 'Lutin 2');")
        # Ingestion manuelle sans started_at (pour contourner init_db purge)
        conn.execute(
            "INSERT INTO scores_defi (lutin_id, year, manche_id, pseudo_lutin, started_at, solved) "
            "VALUES ('l1', 2026, 1, 'Lutin Un', NULL, 0);"
        )
        # Participant ayant démarré
        conn.execute(
            "INSERT INTO scores_defi (lutin_id, year, manche_id, pseudo_lutin, started_at, solved, time_seconds) "
            "VALUES ('l2', 2026, 1, 'Lutin Deux', '2026-10-14T20:00:00+00:00', 1, 28.5);"
        )
    conn.close()

    scores = get_scores_classement(db_path, 2026, manche_id=1)
    assert len(scores) == 1
    assert scores[0]["lutin_id"] == "l2"

    scores_all = get_scores_classement(db_path, 2026)
    assert len(scores_all) == 1
    assert scores_all[0]["lutin_id"] == "l2"


def test_set_edition_status_validation(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo_status.db"
    init_db(db_path)

    # Valid statuses should succeed
    for valid_status in ("draft", "announced", "drawn", "revealed"):
        set_edition_status(db_path, 2026, valid_status)
        assert get_edition_status(db_path, 2026) == valid_status

    # Bogus status should raise ValueError
    with pytest.raises(ValueError, match="Statut d'édition invalide"):
        set_edition_status(db_path, 2026, "bogus")


def test_get_db_connection_has_explicit_busy_timeout(tmp_path: Path) -> None:
    conn = get_db_connection(tmp_path / "t.db")
    try:
        assert conn.execute("PRAGMA busy_timeout;").fetchone()[0] == 5000
    finally:
        conn.close()


def test_init_db_renames_pseudo_lugeur_column_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo_200.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE editions (year INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'draft');
        CREATE TABLE lutins (
            id TEXT PRIMARY KEY, fullname TEXT NOT NULL, email TEXT,
            is_active BOOLEAN NOT NULL DEFAULT 1
        );
        CREATE TABLE scores_defi (
            lutin_id TEXT NOT NULL REFERENCES lutins(id),
            year INTEGER NOT NULL REFERENCES editions(year),
            manche_id INTEGER NOT NULL DEFAULT 1,
            pseudo_lugeur TEXT NOT NULL,
            started_at TIMESTAMP,
            solved BOOLEAN NOT NULL DEFAULT 0,
            time_seconds REAL,
            completed_at TIMESTAMP,
            attempts INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (lutin_id, year, manche_id)
        );
        INSERT INTO editions (year, status) VALUES (2026, 'draft');
        INSERT INTO lutins (id, fullname) VALUES ('l1', 'Lutin 1');
        INSERT INTO scores_defi (lutin_id, year, manche_id, pseudo_lugeur, started_at, solved, time_seconds, attempts)
        VALUES ('l1', 2026, 1, 'Lutin Ancien', '2026-10-19 19:00:00', 1, 45.0, 1);
    """)
    conn.close()

    init_db(db_path)
    init_db(db_path)

    conn = sqlite3.connect(str(db_path))
    cols = [c[1] for c in conn.execute("PRAGMA table_info(scores_defi);").fetchall()]
    row = conn.execute("SELECT pseudo_lutin, time_seconds FROM scores_defi WHERE lutin_id = 'l1';").fetchone()
    conn.close()
    assert "pseudo_lugeur" not in cols
    assert "pseudo_lutin" in cols
    assert row == ("Lutin Ancien", 45.0)


def test_get_or_assign_pseudo_keeps_caller_transaction_open(tmp_path: Path) -> None:
    from pere_noel_fremo.database import begin_immediate, get_db_connection, get_or_assign_pseudo

    db_path = tmp_path / "fremo.db"
    init_db(db_path)

    conn = get_db_connection(db_path)
    try:
        begin_immediate(conn)
        get_or_assign_pseudo(conn, "l1", 2026)
        assert conn.in_transaction is True
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM pseudos;").fetchone()[0] == 0
    finally:
        conn.close()


def test_start_score_defi_rolls_back_pseudo_and_score_together(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pere_noel_fremo.database as database

    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    seed = sqlite3.connect(str(db_path))
    seed.execute("INSERT INTO lutins (id, fullname) VALUES ('l1', 'Lutin Un');")
    seed.execute("INSERT INTO editions (year) VALUES (2026);")
    seed.commit()
    seed.close()

    def boom(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("échec simulé après l'insertion du pseudo")

    monkeypatch.setattr(database, "_get_score_entry", boom)
    with pytest.raises(RuntimeError, match="échec simulé"):
        database.start_score_defi(db_path, "l1", 2026, pseudo_lutin=None)

    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM pseudos;").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM scores_defi;").fetchone()[0] == 0
    finally:
        conn.close()


def test_save_attributions_refuse_des_paires_qui_ne_couvrent_pas_les_confirmes(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    init_db(db_path)
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'announced');")
        for lutin_id in ("l1", "l2", "l3"):
            conn.execute("INSERT INTO lutins (id, fullname) VALUES (?, ?);", (lutin_id, lutin_id))
    conn.close()
    for lutin_id in ("l1", "l2", "l3"):
        set_lutin_presence(db_path, lutin_id, 2026, present=True)

    with pytest.raises(PresencesChangees):
        save_attributions(db_path, 2026, {"l1": "l2", "l2": "l1"})

    assert get_attributions(db_path, 2026) == {}
    assert get_edition_status(db_path, 2026) == "announced"
