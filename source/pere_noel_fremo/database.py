import sqlite3
from pathlib import Path
from typing import Any

import yaml

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lutins (
    id TEXT PRIMARY KEY,
    fullname TEXT NOT NULL,
    email TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exclusions (
    lutin_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    excluded_lutin_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    PRIMARY KEY (lutin_id, excluded_lutin_id)
);

CREATE TABLE IF NOT EXISTS editions (
    year INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tokens (
    token TEXT PRIMARY KEY,
    lutin_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    year INTEGER NOT NULL REFERENCES editions(year) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (lutin_id, year)
);

CREATE TABLE IF NOT EXISTS presences (
    lutin_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    year INTEGER NOT NULL REFERENCES editions(year) ON DELETE CASCADE,
    present BOOLEAN NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (lutin_id, year)
);

CREATE TABLE IF NOT EXISTS scores_defi (
    lutin_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    year INTEGER NOT NULL REFERENCES editions(year) ON DELETE CASCADE,
    pseudo_lugeur TEXT NOT NULL,
    solved BOOLEAN NOT NULL DEFAULT 0,
    time_seconds REAL,
    completed_at TIMESTAMP,
    PRIMARY KEY (lutin_id, year)
);

CREATE TABLE IF NOT EXISTS attributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    donneur_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    beneficiaire_id TEXT NOT NULL REFERENCES lutins(id) ON DELETE CASCADE,
    year INTEGER REFERENCES editions(year) ON DELETE CASCADE,
    order_index INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (donneur_id, beneficiaire_id, order_index)
);
"""


def get_db_connection(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db_connection(path)
    with conn:
        conn.executescript(SCHEMA_SQL)
    return conn


def import_yaml_data(
    db_path: Path | str,
    data_in_path: Path | str,
    secure_data_path: Path | str,
    year: int | None = None,
) -> dict[str, int]:
    """Import lutins, exclusions, et historique cumulé dans SQLite.

    Valide l'intégrité référentielle des données d'entrée et garantit l'idempotence
    sans suppression destructrice.
    """
    with open(data_in_path, encoding="utf-8") as stream:
        data_in = yaml.safe_load(stream) or {}

    secure_data: dict[str, Any] = {}
    if Path(secure_data_path).exists():
        with open(secure_data_path, encoding="utf-8") as stream:
            secure_data = yaml.safe_load(stream) or {}

    # Valider l'intégrité référentielle des exclusions
    all_lutin_ids = set(data_in.keys())
    for lutin_id, params in data_in.items():
        exclusions = params.get("exclude") or []
        for excluded_id in exclusions:
            if excluded_id not in all_lutin_ids:
                raise ValueError(f"Integrity error: lutin '{lutin_id}' excludes unknown lutin '{excluded_id}'")

    conn = init_db(db_path)
    personnes_secure = secure_data.get("personnes", {})

    with conn:
        # Création de l'édition si spécifiée
        if year is not None:
            conn.execute(
                "INSERT OR IGNORE INTO editions (year, status) VALUES (?, 'draft');",
                (year,),
            )

        # 1. Upsert des lutins actifs
        for lutin_id, params in data_in.items():
            fullname = params.get("fullname", lutin_id)
            email = personnes_secure.get(lutin_id, {}).get("email") or params.get("email")
            conn.execute(
                """
                INSERT INTO lutins (id, fullname, email, is_active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                    fullname = excluded.fullname,
                    email = excluded.email,
                    is_active = 1;
                """,
                (lutin_id, fullname, email),
            )

        # Enregistrement des participants historiques passés non actifs pour cette édition
        for _lutin_id, params in data_in.items():
            for historical_id in params.get("history") or []:
                conn.execute(
                    "INSERT OR IGNORE INTO lutins (id, fullname, email, is_active) VALUES (?, ?, NULL, 0);",
                    (historical_id, historical_id),
                )

        # 2. Synchronisation idempotente des exclusions
        for lutin_id, params in data_in.items():
            for excluded_id in params.get("exclude") or []:
                conn.execute(
                    "INSERT OR IGNORE INTO exclusions (lutin_id, excluded_lutin_id) VALUES (?, ?);",
                    (lutin_id, excluded_id),
                )

        # 3. Synchronisation idempotente de l'historique d'attributions
        for lutin_id, params in data_in.items():
            for order_idx, historical_id in enumerate(params.get("history") or []):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO attributions (donneur_id, beneficiaire_id, year, order_index)
                    VALUES (?, ?, NULL, ?);
                    """,
                    (lutin_id, historical_id, order_idx),
                )

        exclusion_count = conn.execute("SELECT COUNT(*) FROM exclusions;").fetchone()[0]
        attribution_count = conn.execute("SELECT COUNT(*) FROM attributions;").fetchone()[0]

    conn.close()
    return {
        "lutins": len(data_in),
        "exclusions": exclusion_count,
        "attributions": attribution_count,
    }


def get_lutins(db_path: Path | str, active_only: bool = True) -> dict[str, dict[str, Any]]:
    """Récupère l'ensemble des lutins avec leurs exclusions et leur historique."""
    conn = get_db_connection(db_path)
    try:
        sql = "SELECT id, fullname, email FROM lutins"
        if active_only:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY id;"
        lutins_rows = conn.execute(sql).fetchall()

        exclusions_rows = conn.execute(
            "SELECT lutin_id, excluded_lutin_id FROM exclusions ORDER BY excluded_lutin_id;"
        ).fetchall()
        exclusions_map: dict[str, list[str]] = {}
        for row in exclusions_rows:
            exclusions_map.setdefault(row["lutin_id"], []).append(row["excluded_lutin_id"])

        history_rows = conn.execute(
            "SELECT donneur_id, beneficiaire_id FROM attributions ORDER BY order_index ASC, id ASC;"
        ).fetchall()
        history_map: dict[str, list[str]] = {}
        for row in history_rows:
            history_map.setdefault(row["donneur_id"], []).append(row["beneficiaire_id"])

        result: dict[str, dict[str, Any]] = {}
        for row in lutins_rows:
            lutin_id = row["id"]
            result[lutin_id] = {
                "fullname": row["fullname"],
                "email": row["email"],
                "exclude": exclusions_map.get(lutin_id, []),
                "history": history_map.get(lutin_id, []),
            }
        return result
    finally:
        conn.close()


def get_lutin_history(db_path: Path | str, lutin_id: str) -> list[str]:
    """Récupère la liste ordonnée de l'historique des bénéficiaires pour un donneur."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT beneficiaire_id FROM attributions WHERE donneur_id = ? ORDER BY order_index ASC, id ASC;",
            (lutin_id,),
        ).fetchall()
        return [row["beneficiaire_id"] for row in rows]
    finally:
        conn.close()


def get_lutin_exclusions(db_path: Path | str, lutin_id: str) -> list[str]:
    """Récupère la liste des exclusions pour un lutin."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT excluded_lutin_id FROM exclusions WHERE lutin_id = ? ORDER BY excluded_lutin_id ASC;",
            (lutin_id,),
        ).fetchall()
        return [row["excluded_lutin_id"] for row in rows]
    finally:
        conn.close()
