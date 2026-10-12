from pathlib import Path

import pytest
import yaml
from pere_noel_fremo.database import (
    complete_score_defi,
    get_attributions,
    get_beneficiaire_for_lutin,
    get_confirmed_lutins,
    get_edition_status,
    get_lutin_exclusions,
    get_lutin_history,
    get_lutins,
    get_or_create_score_defi,
    get_scores_classement,
    import_yaml_data,
    init_db,
    save_attributions,
    set_lutin_presence,
    start_score_defi,
)


def test_init_db_creates_all_required_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    conn = init_db(db_path)

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
    }
    assert required_tables.issubset(tables)


def test_init_db_enables_foreign_keys_and_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    conn1 = init_db(db_path)
    conn1.close()

    conn2 = init_db(db_path)
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

    # Verify helper query functions
    assert get_lutin_history(db_path, "lutin_a") == ["lutin_b", "lutin_c"]
    assert get_lutin_exclusions(db_path, "lutin_a") == ["lutin_b"]

    # Test idempotence: running import a second time updates or preserves without duplicate keys/rows
    counts_repeat = import_yaml_data(db_path, data_in_path, secure_data_path)
    assert counts_repeat["lutins"] == 3

    lutins_after = get_lutins(db_path)
    assert lutins_after["lutin_a"]["history"] == ["lutin_b", "lutin_c"]
    assert lutins_after["lutin_a"]["exclude"] == ["lutin_b"]


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
    conn = init_db(db_path)

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
    conn = init_db(db_path)
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


def test_scores_defi_and_beneficiaire_operations(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    conn = init_db(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l1', 'Lutin 1', 'l1@fremo.org');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l2', 'Lutin 2', 'l2@fremo.org');")
    conn.close()

    # 1. Attributions & get_beneficiaire_for_lutin
    save_attributions(db_path, 2026, {"l1": "l2", "l2": "l1"})
    beneficiaire = get_beneficiaire_for_lutin(db_path, "l1", 2026)
    assert beneficiaire is not None
    assert beneficiaire["id"] == "l2"
    assert beneficiaire["fullname"] == "Lutin 2"

    # Donneur inexistant ou sans attribution
    assert get_beneficiaire_for_lutin(db_path, "l_inconnu", 2026) is None

    # 2. Score Défi cycle de vie
    score = get_or_create_score_defi(db_path, "l1", 2026, "Renne Agile")
    assert score["lutin_id"] == "l1"
    assert score["pseudo_lugeur"] == "Renne Agile"
    assert score["solved"] == 0
    assert score["started_at"] is None

    # Démarrage
    started = start_score_defi(db_path, "l1", 2026)
    assert started["started_at"] is not None

    # Complétion
    completed = complete_score_defi(db_path, "l1", 2026, time_seconds=42.5)
    assert completed["solved"] == 1
    assert completed["time_seconds"] == 42.5

    # Idempotence complétion (ne modifie pas un score déjà résolu)
    completed_again = complete_score_defi(db_path, "l1", 2026, time_seconds=999.0)
    assert completed_again["time_seconds"] == 42.5

    # 3. Classement ordonné
    get_or_create_score_defi(db_path, "l2", 2026, "Lutin Givré")
    complete_score_defi(db_path, "l2", 2026, time_seconds=30.0)

    classement = get_scores_classement(db_path, 2026)
    assert len(classement) == 2
    # l2 (30.0s) doit être 1er devant l1 (42.5s)
    assert classement[0]["pseudo_lugeur"] == "Lutin Givré"
    assert classement[0]["time_seconds"] == 30.0
    assert classement[1]["pseudo_lugeur"] == "Renne Agile"
    assert classement[1]["time_seconds"] == 42.5


def test_scores_defi_multi_manches(tmp_path: Path) -> None:
    db_path = tmp_path / "fremo.db"
    conn = init_db(db_path)
    with conn:
        conn.execute("INSERT INTO editions (year, status) VALUES (2026, 'draft');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l1', 'Lutin 1', 'l1@fremo.org');")
        conn.execute("INSERT INTO lutins (id, fullname, email) VALUES ('l2', 'Lutin 2', 'l2@fremo.org');")
    conn.close()

    # Lutin 1 joue la manche 1 et la manche 2
    score_m1 = get_or_create_score_defi(db_path, "l1", 2026, "Renne Agile", manche_id=1)
    score_m2 = get_or_create_score_defi(db_path, "l1", 2026, "Renne Agile", manche_id=2)
    assert score_m1["manche_id"] == 1
    assert score_m2["manche_id"] == 2

    # Lutin 2 joue seulement la manche 1
    get_or_create_score_defi(db_path, "l2", 2026, "Lutin Givré", manche_id=1)

    # Complétion manche 1 : l2 (25s), l1 (50s)
    complete_score_defi(db_path, "l1", 2026, time_seconds=50.0, manche_id=1)
    complete_score_defi(db_path, "l2", 2026, time_seconds=25.0, manche_id=1)

    # Complétion manche 2 : l1 (35s)
    complete_score_defi(db_path, "l1", 2026, time_seconds=35.0, manche_id=2)

    # Classement Manche 1
    classement_m1 = get_scores_classement(db_path, 2026, manche_id=1)
    assert len(classement_m1) == 2
    assert classement_m1[0]["pseudo_lugeur"] == "Lutin Givré"
    assert classement_m1[0]["time_seconds"] == 25.0
    assert classement_m1[1]["pseudo_lugeur"] == "Renne Agile"
    assert classement_m1[1]["time_seconds"] == 50.0

    # Classement Manche 2
    classement_m2 = get_scores_classement(db_path, 2026, manche_id=2)
    assert len(classement_m2) == 1
    assert classement_m2[0]["pseudo_lugeur"] == "Renne Agile"
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
    conn_migrated = init_db(db_path)
    conn_migrated.close()

    # Vérification que le score existant a manche_id = 1
    scores_m1 = get_scores_classement(db_path, 2026, manche_id=1)
    assert len(scores_m1) == 1
    assert scores_m1[0]["pseudo_lugeur"] == "Lutin Ancien"
    assert scores_m1[0]["time_seconds"] == 45.0
    assert scores_m1[0]["manche_id"] == 1

    # Insertion d'une manche 2 pour le même lutin (doit réussir grâce à la clé composite)
    score_m2 = get_or_create_score_defi(db_path, "l1", 2026, "Lutin Ancien", manche_id=2)
    assert score_m2["manche_id"] == 2

    # Deuxième appel à init_db pour vérifier l'idempotence
    conn_again = init_db(db_path)
    conn_again.close()
    scores_all = get_scores_classement(db_path, 2026)
    assert len(scores_all) == 2
